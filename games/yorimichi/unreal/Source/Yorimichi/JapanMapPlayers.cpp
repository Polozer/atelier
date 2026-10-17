#include "JapanMap.h"
#include "JapanSession.h"
#include "JapanNetwork.h"
#include "JapanGameplayCollision.h"
#include "WandererCharacter.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Engine/World.h"

namespace
{
AWandererCharacter* FindPlayer(UWorld* World, const FString& Id)
{
    const auto* State = World ? World->GetGameState<AJapanGameState>() : nullptr;
    if (!State || Id.IsEmpty()) return nullptr;
    for (const auto& Entry : State->PlayerArray)
        if (const auto* Player = Cast<AJapanPlayerState>(Entry); Player && Player->bWorldReady && Player->SessionPlayerId == Id)
            return Cast<AWandererCharacter>(Player->GetPawn());
    return nullptr;
}
}

void UJapanMap::RefreshPlayerZones() const
{
    TSet<FString> Present;
    const auto* State = Owner ? Owner->GetWorld()->GetGameState<AJapanGameState>() : nullptr;
    if (State) for (const auto& Entry : State->PlayerArray)
    {
        const auto* Player = Cast<AJapanPlayerState>(Entry);
        auto* Pawn = Player && Player->bWorldReady && !Player->SessionPlayerId.IsEmpty() ? Cast<AWandererCharacter>(Player->GetPawn()) : nullptr;
        if (!IsValid(Pawn) || Pawn == Owner || !Pawn->IsReady() || Pawn->IsNpc()) continue;
        const FString Key = TEXT("player_") + Player->SessionPlayerId;
        Present.Add(Key);
        auto* Zone = Zones.FindByPredicate([&](const FJapanMapZone& Z) { return Z.Key == Key; });
        if (!Zone) Zone = &Zones.AddDefaulted_GetRef();
        Zone->Key = Key;
        Zone->Name = Player->RiderName.IsEmpty() ? TEXT("Player") : Player->RiderName;
        Zone->Hint = TEXT("Online player · teleport nearby");
        Zone->Location = Pawn->GetActorLocation();
        Zone->Yaw = Pawn->GetActorRotation().Yaw;
    }
    Zones.RemoveAll([&](const FJapanMapZone& Z) { return Z.Key.StartsWith(TEXT("player_")) && !Present.Contains(Z.Key); });
}

void AWandererCharacter::ServerTravelToPlayer_Implementation(const FString& Id, uint32 Epoch)
{
    if (Epoch != NetworkActivity.Epoch || !bReady || Id.Len() > 128) return;
    auto* Peer = FindPlayer(GetWorld(), Id);
    if (!IsValid(Peer) || Peer == this || !Peer->IsReady())
    { ClientActivityRejected(TEXT("That player is no longer available.")); return; }
    // Choose actual walkable ground near the current authoritative position,
    // including below an airborne rider. Never copy a stale client map position.
    auto Params = JapanGameplayCollision::Query(GetWorld(), SCENE_QUERY_STAT(PlayerMapTravel), false);
    Params.AddIgnoredActor(this); Params.AddIgnoredActor(Peer);
    const auto* Capsule = GetCapsuleComponent();
    const auto* Standing = GetClass()->GetDefaultObject<AWandererCharacter>()->GetCapsuleComponent();
    const float Half = FMath::Max(Capsule->GetScaledCapsuleHalfHeight(), Standing->GetUnscaledCapsuleHalfHeight()*Capsule->GetShapeScale());
    const float Radius = Capsule->GetScaledCapsuleRadius();
    for (int32 I = 0; I < 8; ++I)
    {
        const float Angle = Peer->GetActorRotation().Yaw + 45.f * I;
        const FVector Near = Peer->GetActorLocation() + FRotator(0,Angle,0).Vector()*180.f;
        FHitResult Hit;
        if (!GetWorld()->LineTraceSingleByChannel(Hit, Near+FVector(0,0,100), Near-FVector(0,0,100000), JapanGameplayCollision::Channel, Params) ||
            !GetCharacterMovement()->IsWalkable(Hit) ||
            GetWorld()->OverlapBlockingTestByChannel(Hit.ImpactPoint+FVector(0,0,Half+3), FQuat::Identity,
                JapanGameplayCollision::Channel, FCollisionShape::MakeCapsule(Radius,Half), Params)) continue;
        // Reuse encounter, pending-hit, epoch and travel-rate admission. The
        // short trace retains the selected floor beneath bridges and roofs.
        if (PerformNetworkTravel(Hit.ImpactPoint, Peer->GetActorRotation().Yaw, Epoch, 30.f)) ClientPlayerTravelled();
        return;
    }
    ClientActivityRejected(TEXT("There is no safe ground near that player just now."));
}

void AWandererCharacter::ClientPlayerTravelled_Implementation()
{
    if (GetMap()) GetMap()->Close();
}
