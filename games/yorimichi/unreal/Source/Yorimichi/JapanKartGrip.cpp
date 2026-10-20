#include "JapanKartGrip.h"
#include "WandererCharacter.h"
#include "PlayableCharacter.h"
#include "DrivingComponent.h"
#include "AtelierData.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"

namespace
{
// JSON matrices are column-major Blender metres. Reflect both basis axes and translation
// into UE centimetres once; UE's FMatrix stores basis vectors in rows.
bool ReadFrame(const FJsonObject& Object, const FString& Name, FTransform& Out)
{
    const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
    if (!Object.TryGetArrayField(Name, Values) || Values->Num() != 16) return false;
    double V[16];
    for (int I = 0; I < 16; ++I)
        if (!(*Values)[I]->TryGetNumber(V[I]) || !FMath::IsFinite(V[I])) return false;
    if (FMath::Abs(V[3]) > 1.e-5 || FMath::Abs(V[7]) > 1.e-5 || FMath::Abs(V[11]) > 1.e-5 || FMath::Abs(V[15]-1.) > 1.e-5) return false;
    constexpr double H[3] = {1., -1., 1.};
    FMatrix Matrix = FMatrix::Identity;
    for (int C = 0; C < 3; ++C) for (int R = 0; R < 3; ++R) Matrix.M[C][R] = V[C*4+R] * H[C] * H[R];
    for (int R = 0; R < 3; ++R) Matrix.M[3][R] = V[12+R] * H[R] * 100.;
    Out = FTransform(Matrix);
    return !Out.ContainsNaN() && Out.GetScale3D().GetMin() > .01;
}
}

void ReadKartGrip(AWandererCharacter* Pawn, UDrivingComponent* Car)
{
    Car->SetAuthoredGrips({});
    const FPlayableCharacter* Character = FPlayableCharacter::Find(FPlayableCharacter::NameOf(Pawn));
    const USkeletalMeshComponent* Body = Pawn->GetMesh();
    const USkeletalMesh* Mesh = Body ? Body->GetSkeletalMeshAsset() : nullptr;
    if (!Character || !Mesh) return;
    const TSharedPtr<FJsonObject> Data = AtelierReadJson(AtelierDataPath(TEXT("kart/grips/") + Character->Id + TEXT(".json")));
    if (!Data) return; // The grip editor has not saved this character yet.
    const TSharedPtr<FJsonObject>* Hands = nullptr;
    const TSharedPtr<FJsonObject>* Bind = nullptr;
    FString Id;
    double Schema = 0., Scale = 0.;
    if (!Data->TryGetNumberField(TEXT("schema"), Schema) || Schema != 1. ||
        !Data->TryGetStringField(TEXT("character"), Id) || Id != Character->Id ||
        !Data->TryGetNumberField(TEXT("scale"), Scale) || !FMath::IsFinite(Scale) || FMath::Abs(Scale-Car->GetKartScale()) > .002 ||
        !Data->TryGetObjectField(TEXT("hands"), Hands) || !Data->TryGetObjectField(TEXT("bind_world"), Bind))
    {
        UE_LOG(LogTemp, Error, TEXT("Kart grip is invalid or stale for %s"), *Character->Id); return;
    }
    const FReferenceSkeleton& Ref = Mesh->GetRefSkeleton();
    TMap<FName, FTransform> Frames;
    for (const TCHAR* Side : {TEXT("L"), TEXT("R")})
    {
        const TSharedPtr<FJsonObject>* Hand = nullptr;
        if (!(*Hands)->TryGetObjectField(Side, Hand)) return;
        TArray<FString> Names = {FString::Printf(TEXT("hand_%s"), Side)};
        for (int F = 0; F < 5; ++F) for (int K = 0; K < 3; ++K)
        {
            const TCHAR* const Finger[] = {TEXT("finger_"), TEXT("finger_tip_"), TEXT("finger_end_")};
            const TCHAR* const Thumb[] = {TEXT("thumb_"), TEXT("thumb_tip_"), TEXT("thumb_end_")};
            Names.Add(F < 4 ? FString::Printf(TEXT("%s%d_%s"), Finger[K], F, Side) : FString::Printf(TEXT("%s%s"), Thumb[K], Side));
        }
        for (const FString& Name : Names)
        {
            const FName Bone = Pawn->GetSkateBone(FName(*Name));
            const int Index = Ref.FindBoneIndex(Bone);
            FTransform Local, BlenderBind;
            if (Index == INDEX_NONE || !ReadFrame(**Hand, Name, Local) || !ReadFrame(**Bind, Name, BlenderBind))
            {
                UE_LOG(LogTemp, Error, TEXT("Kart grip missing bone/frame %s"), *Name); return;
            }
            FTransform UEReference = FTransform::Identity;
            for (int I = Index; I != INDEX_NONE; I = Ref.GetParentIndex(I)) UEReference = UEReference * Ref.GetRefBonePose()[I];
            // Blender's prepared world is actor-forward. FBX may use different bone axes and a
            // mesh-facing rotation: calibrate those axes from both bind skeletons, never guessed Euler angles.
            const FQuat Correction = BlenderBind.GetRotation().Inverse() * Body->GetRelativeRotation().Quaternion() * UEReference.GetRotation();
            Local.SetRotation((Local.GetRotation() * Correction).GetNormalized());
            Frames.Add(Bone, Local);
        }
    }
    const TSharedPtr<FJsonObject>* Poles = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Left = nullptr;
    if (!Data->TryGetObjectField(TEXT("arm_poles"), Poles) || !(*Poles)->TryGetArrayField(TEXT("L"), Left) || Left->Num() != 3) return;
    double Pole[3];
    for (int I = 0; I < 3; ++I) if (!(*Left)[I]->TryGetNumber(Pole[I]) || !FMath::IsFinite(Pole[I])) return;
    double Lean = 0., Height = 0., Tilt = 0.;
    if (!Data->TryGetNumberField(TEXT("shoulder_lean_degrees"), Lean) || !FMath::IsFinite(Lean) || Lean < -15. || Lean > 45. ||
        !Data->TryGetNumberField(TEXT("wheel_height_offset"), Height) || !FMath::IsFinite(Height) || FMath::Abs(Height) > .25) return;
    if (!Data->TryGetNumberField(TEXT("wheel_tilt_offset_degrees"), Tilt) || !FMath::IsFinite(Tilt) || Tilt < -35.001 || Tilt > 25.001) return;
    Car->SetAuthoredFit(Lean, Height * 100., Tilt);
    Car->SetAuthoredElbow(FVector(Pole[0], -Pole[1], Pole[2]) * 100.);
    Car->SetAuthoredGrips(MoveTemp(Frames));
}
