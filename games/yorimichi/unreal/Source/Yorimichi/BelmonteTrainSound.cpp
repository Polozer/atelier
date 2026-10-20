// The Belmonte train's sounds (assets/audio/train/make.py, imported to /Game/Audio/Train by unreal.sounds), played from
// the train's own motion: the service places every train from the shared clock on every machine, and the sound follows
// the same pure functions (BelmonteTrainRules::SoundMix, FBelmonteTrainLine::Stands), so a host and its guests hear the
// train they see, accelerating and braking with it, without replicating anything more.
#include "BelmonteTrainService.h"
#include "BelmonteTrainRules.h"
#include "Components/AudioComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundAttenuation.h"
#include "Sound/SoundWave.h"
#include "Engine/World.h"

namespace
{
/** make.py's: the roll master's speed (m/s, pitch 1 there) and the rail length (m, one clack per bogie per joint). */
constexpr double RollSpeed = 22., RailLength = 25.;
/** Clacks are spawned only for vehicles within this distance of the listener (cm): they are short and local. */
constexpr double ClackReach = 12000.;

USoundWave* LoadTrainWave(const TCHAR* Cue)
{
    const FString Name = FString::Printf(TEXT("%s_01"), Cue);
    return LoadObject<USoundWave>(nullptr, *FString::Printf(TEXT("/Game/Audio/Train/%s.%s"), *Name, *Name), nullptr, LOAD_NoWarn | LOAD_Quiet);
}

USoundAttenuation* MakeAttenuation(UObject* Outer, float Inner, float Falloff)
{
    auto* Attenuation = NewObject<USoundAttenuation>(Outer);
    FSoundAttenuationSettings& A = Attenuation->Attenuation;
    A.bAttenuate = true; A.bSpatialize = true; A.AttenuationShape = EAttenuationShape::Sphere;
    A.AttenuationShapeExtents = FVector(Inner, 0.f, 0.f); A.FalloffDistance = Falloff;
    A.DistanceAlgorithm = EAttenuationDistanceModel::NaturalSound; A.dBAttenuationAtMax = -60.f;
    return Attenuation;
}

/** A loop on a vehicle at its mix volume and pitch: started when audible, stopped when silent. */
void Drive(UAudioComponent* Loop, float Volume, float Pitch, int32 Seed)
{
    if (!Loop) return;
    if (Volume > .01f)
    {
        if (!Loop->IsPlaying()) Loop->Play(FMath::Fmod(float(Seed) * 1.7f, 4.f));    // vehicles out of step
        Loop->SetVolumeMultiplier(Volume);
        Loop->SetPitchMultiplier(Pitch);
    }
    else if (Loop->IsPlaying()) Loop->Stop();
}
}

void ABelmonteTrainService::LoadSounds()
{
    TrainStands.Reset();
    for (int32 Train = 0; Train < Line.Trains.Num(); ++Train) TrainStands.Add(Line.Stands(Train));
    LastBogies.Init(FVector2D(TNumericLimits<double>::Max()), Vehicles.Num());
    if (IsRunningDedicatedServer() || !GetWorld() || !GetWorld()->bAllowAudioPlayback) return;
    USoundWave* Roll = LoadTrainWave(TEXT("roll"));
    USoundWave* Idle = LoadTrainWave(TEXT("idle"));
    USoundWave* Effort = LoadTrainWave(TEXT("effort"));
    ClackSound = LoadTrainWave(TEXT("clack"));
    BrakeSound = LoadTrainWave(TEXT("brake"));
    DepartSound = LoadTrainWave(TEXT("depart"));
    // A coach rolling by is heard from the platform and the lineside (about 90 m); the locomotive and its signals further.
    RollAttenuation = MakeAttenuation(this, 1200.f, 8000.f);
    SignalAttenuation = MakeAttenuation(this, 2500.f, 16000.f);
    auto Loop = [this](USceneComponent* Body, USoundWave* Wave, const TCHAR* Name, int32 Index, USoundAttenuation* Attenuation, double Z)
    {
        auto* L = NewObject<UAudioComponent>(this, *FString::Printf(TEXT("Train%s%d"), Name, Index));
        L->SetupAttachment(Body);
        L->SetRelativeLocation(FVector(0., 0., Z));
        L->bAutoActivate = false; L->bAllowSpatialization = true;
        L->AttenuationSettings = Attenuation;
        L->SetSound(Wave);
        L->RegisterComponent();
        return L;
    };
    for (int32 I = 0; I < Vehicles.Num(); ++I) RollLoops.Add(Roll ? Loop(Vehicles[I].Body, Roll, TEXT("Roll"), I, RollAttenuation, 60.) : nullptr);
    for (int32 Train = 0; Train < Line.Trains.Num(); ++Train)
    {
        const FVehicle* Engine = Vehicles.FindByPredicate([Train](const FVehicle& V) { return V.Train == Train && V.Id == TEXT("locomotive"); });
        if (!Engine) Engine = Vehicles.FindByPredicate([Train](const FVehicle& V) { return V.Train == Train; });
        UStaticMeshComponent* Body = Engine ? Engine->Body.Get() : nullptr;
        IdleLoops.Add(Body && Idle ? Loop(Body, Idle, TEXT("Idle"), Train, SignalAttenuation, 250.) : nullptr);
        EffortLoops.Add(Body && Effort ? Loop(Body, Effort, TEXT("Effort"), Train, SignalAttenuation, 250.) : nullptr);
    }
    int32 Stands = 0;
    for (const auto& S : TrainStands) Stands += S.Num();
    UE_LOG(LogTemp, Display, TEXT("TRAIN SOUNDS roll=%d idle=%d effort=%d clack=%d brake=%d depart=%d stands=%d"), Roll != nullptr, Idle != nullptr,
        Effort != nullptr, ClackSound != nullptr, BrakeSound != nullptr, DepartSound != nullptr, Stands);
}

void ABelmonteTrainService::UpdateSounds(double Time, float Dt)
{
    const double Previous = LastSoundTime;
    LastSoundTime = Time;
    const double Scale = FMath::Max(ClockScale(), 1e-3);
    auto Engine = [this](int32 Train) -> UStaticMeshComponent*
    {
        if (IdleLoops.IsValidIndex(Train) && IdleLoops[Train]) return Cast<UStaticMeshComponent>(IdleLoops[Train]->GetAttachParent());
        for (const FVehicle& V : Vehicles) if (V.Train == Train && V.Id == TEXT("locomotive")) return V.Body;
        for (const FVehicle& V : Vehicles) if (V.Train == Train) return V.Body;
        return nullptr;
    };
    auto Play = [&](USoundWave* Wave, USceneComponent* At, float Pitch)
    {
        if (Wave && At && SignalAttenuation)
            UGameplayStatics::SpawnSoundAttached(Wave, At, NAME_None, FVector(0., 0., 250.), EAttachLocation::KeepRelativeOffset, true,
                1.f, Pitch, 0.f, SignalAttenuation);
    };
    // The cues of each stand: the brakes from the deceleration to the stop, the departure signal as it moves off.
    if (Previous >= 0.)
        for (int32 Train = 0; Train < TrainStands.Num(); ++Train)
            for (const FBelmonteTrainStand& Stand : TrainStands[Train])
            {
                float Pitch = 1.f;
                const double BrakeAt = BelmonteTrainRules::BrakeCue(Stand.BrakeStart, Stand.Arrive, BrakeSound ? BrakeSound->Duration : 0., Scale, Pitch);
                if (BelmonteTrainRules::EventDue(BrakeAt, Previous, Time, Line.Cycle)) { Play(BrakeSound, Engine(Train), Pitch); ++SoundEvents[0]; }
                if (BelmonteTrainRules::EventDue(Stand.Depart, Previous, Time, Line.Cycle)) { Play(DepartSound, Engine(Train), 1.f); ++SoundEvents[1]; }
            }
    // The continuous layers, from each train's speed and acceleration as heard (service rates times the clock's scale).
    TArray<BelmonteTrainRules::FTrainSoundMix, TInlineAllocator<4>> Mixes;
    for (int32 Train = 0; Train < Line.Trains.Num(); ++Train)
    {
        const double Speed = FMath::Abs(Line.Speed(Train, Time)) * Scale;
        const double Accel = (FMath::Abs(Line.Speed(Train, Time + .5)) - FMath::Abs(Line.Speed(Train, Time - .5))) * Scale * Scale;
        Mixes.Add(BelmonteTrainRules::SoundMix(Speed, Accel, RollSpeed));
        Drive(IdleLoops.IsValidIndex(Train) ? IdleLoops[Train].Get() : nullptr, Mixes.Last().Idle, 1.f, Train);
        Drive(EffortLoops.IsValidIndex(Train) ? EffortLoops[Train].Get() : nullptr, Mixes.Last().Effort, Mixes.Last().EffortPitch, Train);
    }
    LastMixes.Reset(); LastMixes.Append(Mixes);
    // The roll on every vehicle; a clack for each rail joint one of its bogies passed this frame, near the listener.
    FVector Ear = FVector::ZeroVector, Front, Right;
    const APlayerController* PC = GetWorld()->GetFirstPlayerController();
    if (PC) PC->GetAudioListenerPosition(Ear, Front, Right);
    const bool bEar = PC != nullptr;
    for (int32 I = 0; I < Vehicles.Num(); ++I)
    {
        const FVehicle& V = Vehicles[I];
        if (!Mixes.IsValidIndex(V.Train)) continue;
        const BelmonteTrainRules::FTrainSoundMix& M = Mixes[V.Train];
        Drive(RollLoops.IsValidIndex(I) ? RollLoops[I].Get() : nullptr, M.Roll, M.RollPitch, I);
        const double Centre = Line.Chainage(V.Train, Time) + V.Offset;
        const FVector2D Bogies(Centre + V.BogieA, Centre + V.BogieB);
        const FVector2D Last = LastBogies.IsValidIndex(I) ? LastBogies[I] : Bogies;
        if (LastBogies.IsValidIndex(I)) LastBogies[I] = Bogies;
        if (Last.X == TNumericLimits<double>::Max() || M.Clack <= .01f) continue;
        const bool bNear = ClackSound && bEar && FVector::DistSquared(Ear, V.Body->GetComponentLocation()) < FMath::Square(ClackReach);
        for (int32 B = 0; B < 2; ++B)
        {
            const int32 Joints = BelmonteTrainRules::JointsCrossed(Last[B], Bogies[B], RailLength);
            SoundEvents[2] += Joints;
            if (Joints && bNear)
                UGameplayStatics::SpawnSoundAttached(ClackSound, V.Body, NAME_None, FVector((B ? V.BogieB : V.BogieA) * 100., 0., 40.),
                    EAttachLocation::KeepRelativeOffset, true, M.Clack, M.ClackPitch * FMath::FRandRange(.97f, 1.03f), 0.f, RollAttenuation);
        }
    }
}
