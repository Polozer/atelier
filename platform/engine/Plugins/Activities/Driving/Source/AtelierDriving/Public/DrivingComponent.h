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

namespace AtelierDrivingSide
{
/** The rider's left hand/foot is side 0; Unreal component space puts it at -Y. */
constexpr float Sign(int Side) { return Side ? 1.f : -1.f; }
static_assert(Sign(0) == -1.f, "side 0 is the rider's left, at component -Y");
static_assert(Sign(1) == 1.f, "side 1 is the rider's right, at component +Y");
}

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

    /** The three meshes: body (origin on the ground under its middle, +X the nose), one wheel (axle +Y, origin at
     *  the axle) and the steering wheel (plane faces +X, origin at the hub). Missing content falls back to a box. */
    void SetMeshes(const FSoftObjectPath& Body, const FSoftObjectPath& Seat, const FSoftObjectPath& Wheel,
                   const FSoftObjectPath& Steering);
    /** Whole-kart scale around the driver; the anim instance fits it to the rider's leg length. */
    void SetKartScale(float Scale);
    float GetKartScale() const { return KartScale; }
    /** Slides the seat back along the frame for a taller driver (cm, 0..4), as a kart's seat does. */
    void SetSeatSlide(float Cm);
    float GetSeatSlide() const { return SeatSlide; }

    /** The kart's own frame (centimetres, origin on the ground under its middle, +X the nose): where the driver sits
     *  and grips, for the animation stance. */
    FVector PosePoint(const FVector& Local) const;
    FVector PoseDirection(const FVector& Local) const;
    FVector SeatPoint() const { return FVector(-24.f - SeatSlide, 0, 26); }
    FVector HandPoint(int32 Side) const;
    FVector ElbowPoint(int32 Side) const { return FVector(2, Side ? 32.f : -32.f, 38); }
    FVector FootPoint(int32 Side) const { return FVector(32.f + SeatSlide * 2.f, Side ? 14.f : -14.f, 17); }
    FVector KneePoint(int32 Side) const { return FVector(20, Side ? 18.f : -18.f, 40); }
    FVector GripForward(int32 Side) const;
    FVector GripUp(int32 Side) const;
    FVector GripAxis(int32 Side) const;
    /** The channel the car reads the world on (default ECC_Visibility). */
    void SetTraceChannel(ECollisionChannel InChannel) { TraceChannel = InChannel; }

private:
    bool Summon();
    bool Dismount();
    void EndDrive(const FVector& GroundSpot);
    /** Restore the rider and hide the kart without moving the actor (forced cleanup keeps the capsule centre). */
    void FinishDrive();
    bool StandingRoom(const FVector& Ground) const;
    void Recover();
    void UpdatePose(float DeltaSeconds);
    bool GroundBelow(const FVector& At, float Reach, FVector& Out) const;
    bool FreeAt(const FVector& At, const FQuat& Rotation) const;
    void FindGroundOffset();

    UPROPERTY() TObjectPtr<ACharacter> Rider;
    UPROPERTY() TObjectPtr<USceneComponent> CarRoot;
    UPROPERTY() TObjectPtr<UStaticMeshComponent> Body;
    UPROPERTY() TObjectPtr<UStaticMeshComponent> Seat;
    UPROPERTY() TObjectPtr<UStaticMeshComponent> Wheel[4];
    UPROPERTY() TObjectPtr<UStaticMeshComponent> Steering;
    UPROPERTY() TObjectPtr<UStaticMesh> BodyMesh;
    UPROPERTY() TObjectPtr<UStaticMesh> SeatMesh;
    UPROPERTY() TObjectPtr<UStaticMesh> WheelMesh;
    UPROPERTY() TObjectPtr<UStaticMesh> SteeringMesh;
    TSharedPtr<FDrivingCar> Car;
    ECollisionChannel TraceChannel = ECC_Visibility;
    FSoftObjectPath BodyMeshPath;
    FSoftObjectPath SeatMeshPath;
    FSoftObjectPath WheelMeshPath;
    FSoftObjectPath SteeringMeshPath;
    FVector2D MoveInput = FVector2D::ZeroVector;
    FString Hint;
    float GroundOffset = 0.f;
    float BodyLift = 0.f;
    float KartScale = 1.f;
    float SeatSlide = 0.f;
    float Spin[4] = {0.f, 0.f, 0.f, 0.f};
    FQuat SteeringBase = FQuat::Identity;
    FVector LastGround = FVector::ZeroVector;
    bool bHandbrake = false;
    bool bEquipped = false;
    bool bHasGround = false;
    bool bSavedUseControllerYaw = false;
};
