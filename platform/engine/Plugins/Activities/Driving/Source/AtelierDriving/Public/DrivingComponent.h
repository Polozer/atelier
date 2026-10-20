#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Engine/EngineTypes.h"
#include "UObject/SoftObjectPath.h"
#include "DrivingComponent.generated.h"

class ACharacter;
class UPrimitiveComponent;
class USceneComponent;
class UStaticMesh;
class UStaticMeshComponent;
struct FDrivingCar;

/** Drives a four-wheel car from a character: summons it onto the ground beside the rider, mounts, steps the simulation
 *  at its fixed 60 Hz, and puts the rider back on their feet beside it. The simulation owns the chassis; this component
 *  only reads the world (a ray per wheel) and moves the actor it is attached to. */
UCLASS(ClassGroup=(Atelier), meta=(BlueprintSpawnableComponent))
class ATELIERDRIVING_API UDrivingComponent : public UActorComponent
{
    GENERATED_BODY()
public:
    UDrivingComponent();
    virtual ~UDrivingComponent() override;
    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

    void Initialize(ACharacter* InRider);
    /** Summon and mount, or (stopped) step off and park. False with the reason in GetStatus(). */
    bool Toggle();
    void StowImmediately();

    bool IsEquipped() const { return bEquipped; }
    bool IsDriving() const { return bEquipped; }
    /** Ground speed in centimetres per second (the game's unit). */
    float GetSpeed() const;
    float GetSpeedKph() const;
    FString GetStatus() const { return Hint; }
    /** The chassis pose: origin at the centre of gravity, +X the nose. */
    FTransform GetCarTransform() const;

    /** Intent from the rider: Move.X steers (right positive), Move.Y drives (forward) or brakes (back). */
    void SetInput(FVector2D Move);
    void SetHandbrake(bool bOn) { bHandbrake = bOn; }

    /** The car body mesh: its origin on the ground under its middle, +X the nose. Missing content falls back to a box. */
    void SetBodyMesh(const FSoftObjectPath& Mesh);
    /** The channel the car reads the world on (default ECC_Visibility). */
    void SetTraceChannel(ECollisionChannel InChannel) { TraceChannel = InChannel; }

private:
    bool Summon();
    void Dismount();
    void EndDrive(const FVector& GroundSpot);
    void Recover();
    void UpdatePose();
    FVector GroundBelow(const FVector& At, float Reach) const;
    bool FreeAt(const FVector& At, const FQuat& Rotation) const;
    void FindGroundOffset();

    UPROPERTY() TObjectPtr<ACharacter> Rider;
    UPROPERTY() TObjectPtr<USceneComponent> CarRoot;
    UPROPERTY() TObjectPtr<UStaticMeshComponent> Body;
    UPROPERTY() TObjectPtr<UStaticMesh> BodyMesh;
    TSharedPtr<FDrivingCar> Car;
    ECollisionChannel TraceChannel = ECC_Visibility;
    FSoftObjectPath BodyMeshPath;
    FVector2D MoveInput = FVector2D::ZeroVector;
    FString Hint;
    float GroundOffset = 0.f;
    float BodyLift = 0.f;
    FVector LastGround = FVector::ZeroVector;
    bool bHandbrake = false;
    bool bEquipped = false;
    bool bHasGround = false;
    bool bSavedUseControllerYaw = false;
};
