#include "DrivingComponent.h"

#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "UObject/ConstructorHelpers.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Simulation/SimulationKart.h"
#include "Simulation/SimulationVehicle.h"

using namespace atelier::driving;

namespace
{
FVector ToUE(const Vec3& V)
{
    return FVector(V.z, V.x, V.y) * 100.f;
}

FVector ToUEDir(const Vec3& V)
{
    return FVector(V.z, V.x, V.y);
}

Vec3 ToSim(const FVector& V)
{
    return Vec3{float(V.Y) * .01f, float(V.Z) * .01f, float(V.X) * .01f};
}

Vec3 ToSimDir(const FVector& V)
{
    return Vec3{float(V.Y), float(V.Z), float(V.X)};
}

FQuat ToUE(const Quat& Q)
{
    return FQuat(Q.z, Q.x, Q.y, Q.w);
}

/** The simulation's only world interface: a ray per wheel, plus the body rays the step makes for the chassis. */
struct FCarGround final : Ground
{
    UWorld* World = nullptr;
    const AActor* Ignore = nullptr;
    ECollisionChannel Channel = ECC_Visibility;

    FCarGround() = default;
    FCarGround(UWorld* InWorld, const AActor* InIgnore, ECollisionChannel InChannel)
        : World(InWorld), Ignore(InIgnore), Channel(InChannel)
    {}

    bool hit(Vec3 Origin, Vec3 Dir, float MaxDistance, GroundHit& Out) const override
    {
        if (!World || MaxDistance <= 0.f)
        {
            return false;
        }
        const FVector From = ToUE(Origin);
        const FHitResult Result = [&]
        {
            FHitResult Hit;
            FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingGround), false, Ignore);
            World->LineTraceSingleByChannel(Hit, From, From + ToUEDir(Dir) * (MaxDistance * 100.f), Channel, Params);
            return Hit;
        }();
        if (!Result.bBlockingHit && !Result.bStartPenetrating)
        {
            return false;
        }
        Out.distance = FVector::Dist(From, Result.ImpactPoint) * .01f;
        Out.normal = ToSimDir(Result.ImpactNormal);
        if (Out.normal.y <= 0.f)
        {
            return false;
        }
        Out.surface = SurfaceGrip{};
        return true;
    }
};
} // namespace

struct FDrivingCar
{
    explicit FDrivingCar(const VehicleSpec& InSpec) : Chassis(InSpec) {}
    Vehicle Chassis;
    float Accumulator = 0.f;
};

UDrivingComponent::UDrivingComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
    static ConstructorHelpers::FObjectFinder<UStaticMesh> Column(TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));
    ColumnMesh = Column.Object;
}

UDrivingComponent::~UDrivingComponent() = default;

void UDrivingComponent::Initialize(ACharacter* InRider)
{
    Rider = InRider;
    if (!Rider || CarRoot)
    {
        return;
    }
    CarRoot = NewObject<USceneComponent>(this, TEXT("CarRoot"));
    Rider->AddInstanceComponent(CarRoot);
    CarRoot->RegisterComponent();
    CarRoot->AttachToComponent(Rider->GetRootComponent(), FAttachmentTransformRules::KeepRelativeTransform);
    Body = NewObject<UStaticMeshComponent>(this, TEXT("CarBody"));
    Rider->AddInstanceComponent(Body);
    Body->SetupAttachment(CarRoot);
    Body->RegisterComponent();
    Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Body->SetVisibility(false, true);
    Body->SetCastShadow(true);
    Seat = NewObject<UStaticMeshComponent>(this, TEXT("CarSeat"));
    Rider->AddInstanceComponent(Seat);
    Seat->SetupAttachment(Body);
    Seat->RegisterComponent();
    Seat->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Seat->SetVisibility(false, true);
    for (int i = 0; i < 4; ++i)
    {
        Wheel[i] = NewObject<UStaticMeshComponent>(this, *FString::Printf(TEXT("CarWheel%d"), i));
        Rider->AddInstanceComponent(Wheel[i]);
        Wheel[i]->SetupAttachment(Body);
        Wheel[i]->RegisterComponent();
        Wheel[i]->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        Wheel[i]->SetVisibility(false, true);
    }
    Steering = NewObject<UStaticMeshComponent>(this, TEXT("CarSteeringWheel"));
    Rider->AddInstanceComponent(Steering);
    Steering->SetupAttachment(Body);
    Steering->RegisterComponent();
    Steering->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Steering->SetVisibility(false, true);
    SteeringColumn = NewObject<UStaticMeshComponent>(this, TEXT("SteeringColumn"));
    Rider->AddInstanceComponent(SteeringColumn);
    SteeringColumn->SetupAttachment(Body);
    SteeringColumn->SetStaticMesh(ColumnMesh);
    SteeringColumn->RegisterComponent();
    SteeringColumn->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    SteeringColumn->SetVisibility(false, true);
}

bool UDrivingComponent::Configure(const FDrivingCockpit& InCockpit)
{
    if (bEquipped) return false;
    bConfigured = false;
    Hint = TEXT("Kart cockpit data is invalid");
    if (!Rider || InCockpit.ReferenceLegLength <= 0.f || InCockpit.SteeringRadius <= 0.f ||
        InCockpit.MinScale <= 0.f || InCockpit.MaxScale < InCockpit.MinScale ||
        InCockpit.WheelRadius <= 0.f || InCockpit.WheelWidth <= 0.f)
        return false;
    const USkeletalMesh* Mesh = Rider->GetMesh()->GetSkeletalMeshAsset();
    if (!Mesh) return false;
    const FReferenceSkeleton& Ref = Mesh->GetRefSkeleton();
    auto Point = [&Ref](const TCHAR* Name)
    {
        FTransform T = FTransform::Identity;
        for (int32 I = Ref.FindBoneIndex(Name); I != INDEX_NONE; I = Ref.GetParentIndex(I)) T = T * Ref.GetRefBonePose()[I];
        return T.GetLocation();
    };
    if (Ref.FindBoneIndex(TEXT("thigh_L")) == INDEX_NONE || Ref.FindBoneIndex(TEXT("shin_L")) == INDEX_NONE ||
        Ref.FindBoneIndex(TEXT("foot_L")) == INDEX_NONE) return false;
    const float Leg = FVector::Dist(Point(TEXT("thigh_L")), Point(TEXT("shin_L"))) + FVector::Dist(Point(TEXT("shin_L")), Point(TEXT("foot_L")));
    const float Scale = Leg / InCockpit.ReferenceLegLength;
    if (!FMath::IsFinite(Scale) || Scale < InCockpit.MinScale || Scale > InCockpit.MaxScale)
    {
        Hint = FString::Printf(TEXT("Kart does not fit this character (scale %.3f; allowed %.2f to %.2f)"), Scale, InCockpit.MinScale, InCockpit.MaxScale);
        return false;
    }
    Cockpit = InCockpit;
    SetKartScale(Scale);
    SteeringBase = FQuat(FVector::RightVector, FMath::DegreesToRadians(Cockpit.SteeringTilt));
    Steering->SetRelativeLocation(Cockpit.Steering);
    Steering->SetRelativeRotation(SteeringBase);
    Seat->SetRelativeLocation(Cockpit.Seat);
    SetAuthoredFit(0.f, 0.f, 0.f);
    bConfigured = true;
    return true;
}

void UDrivingComponent::SetMeshes(const FSoftObjectPath& BodyPath, const FSoftObjectPath& SeatPath,
                                  const FSoftObjectPath& WheelPath, const FSoftObjectPath& SteeringPath)
{
    BodyMeshPath = BodyPath;
    SeatMeshPath = SeatPath;
    WheelMeshPath = WheelPath;
    SteeringMeshPath = SteeringPath;
    BodyMesh = Cast<UStaticMesh>(BodyPath.TryLoad());
    SeatMesh = Cast<UStaticMesh>(SeatPath.TryLoad());
    WheelMesh = Cast<UStaticMesh>(WheelPath.TryLoad());
    SteeringMesh = Cast<UStaticMesh>(SteeringPath.TryLoad());
    if (SteeringColumn && SteeringMesh)
        if (UMaterialInstanceDynamic* Paint = SteeringColumn->CreateDynamicMaterialInstance(0, SteeringMesh->GetMaterial(0)))
            Paint->SetVectorParameterValue(TEXT("Tint"), FLinearColor(.285f, .27f, .22f));
}

void UDrivingComponent::SetKartScale(float Scale)
{
    if (bEquipped) return;
    KartScale = FMath::Clamp(Scale, .5f, 2.f);
    if (Body)
    {
        Body->SetRelativeScale3D(FVector(KartScale));
    }
}

bool UDrivingComponent::Toggle()
{
    if (bEquipped)
    {
        if (GetSpeed() > 60.f)
        {
            Hint = TEXT("Stop first");
            return false;
        }
        return Dismount();
    }
    return Summon();
}

void UDrivingComponent::StowImmediately()
{
    if (!bEquipped)
    {
        return;
    }
    if (!Dismount())
    {
        // Forced cleanup (world change, character switch): keep the capsule centre as it is; no floor shift.
        FinishDrive();
    }
}

bool UDrivingComponent::GroundBelow(const FVector& At, float Reach, FVector& Out) const
{
    if (!Rider || !Rider->GetWorld())
    {
        return false;
    }
    FHitResult Hit;
    FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingPlace), false, Rider);
    const FVector From = At + FVector(0, 0, Reach * .5f);
    if (Rider->GetWorld()->LineTraceSingleByChannel(Hit, From, From - FVector(0, 0, Reach * 1.5f), TraceChannel, Params) &&
        Hit.ImpactNormal.Z > .55f)
    {
        Out = Hit.ImpactPoint;
        return true;
    }
    return false;
}

bool UDrivingComponent::FreeAt(const FVector& At, const FQuat& Rotation) const
{
    if (!Rider || !Rider->GetWorld())
    {
        return false;
    }
    FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingPlace), false, Rider);
    const FCollisionShape Shape = FCollisionShape::MakeBox(Cockpit.BodyHalfExtents * (KartScale * .88f));
    return !Rider->GetWorld()->OverlapBlockingTestByChannel(At, Rotation, TraceChannel, Shape, Params);
}

void UDrivingComponent::FindGroundOffset()
{
    if (!Car)
    {
        GroundOffset = 0.f;
        return;
    }
    const VehicleSpec& Spec = Car->Chassis.spec_ref();
    GroundOffset = (Spec.dimension.y + inch_to_m(Spec.chassis.ride_height[0])) * 100.f;
}

bool UDrivingComponent::Summon()
{
    if (bRequireAuthoredGrips && !HasAuthoredGrips())
    {
        Hint = TEXT("This character's kart grip is not ready: save and import its grip pose"); return false;
    }
    if (!Rider || !Rider->GetWorld() || !Body || !bConfigured || !BodyMesh || !SeatMesh || !WheelMesh || !SteeringMesh)
    {
        if (Hint.IsEmpty()) Hint = TEXT("The car is not ready");
        return false;
    }
    if (Rider->GetCharacterMovement()->IsFalling())
    {
        Hint = TEXT("Land first");
        return false;
    }
    const FRotator Yaw(0.f, Rider->GetActorRotation().Yaw, 0.f);
    const FRotationMatrix Basis(Yaw);
    const FVector Right = Basis.GetUnitAxis(EAxis::Y);
    const FVector Forward = Basis.GetUnitAxis(EAxis::X);
    const FVector Base = Rider->GetActorLocation();
    const FVector Candidates[] = {Base + Right * 190.f, Base - Right * 190.f, Base - Forward * 460.f};
    FVector Spot = FVector::ZeroVector;
    bool bFound = false;
    for (const FVector& Candidate : Candidates)
    {
        FVector Ground;
        if (!GroundBelow(Candidate, 320.f, Ground))
        {
            continue;
        }
        if (FreeAt(Ground + FVector(0, 0, 30.f), Yaw.Quaternion()))
        {
            Spot = Ground;
            bFound = true;
            break;
        }
    }
    if (!bFound)
    {
        Hint = TEXT("No room for the car");
        return false;
    }

    VehicleSpec Spec = kart_spec();
    Spec.dimension = ToSim(Cockpit.BodyHalfExtents) * KartScale;
    Spec.chassis.wheel_base = (Cockpit.WheelPositions[0].X - Cockpit.WheelPositions[2].X) * .01f * KartScale;
    Spec.chassis.front_axle = Cockpit.WheelPositions[0].X * .01f * KartScale;
    for (int I = 0; I < 2; ++I)
    {
        Spec.chassis.track_width[I] = FMath::Abs(Cockpit.WheelPositions[I*2].Y - Cockpit.WheelPositions[I*2+1].Y) * .01f * KartScale;
        Spec.chassis.ride_height[I] *= KartScale; Spec.chassis.travel[I] *= KartScale;
        const float Size = I == 0 ? 1.f : 1.08f;
        Spec.tires.rim_size[I] *= KartScale * Size;
        Spec.tires.section_width[I] = Cockpit.WheelWidth * 10.f * KartScale * Size;
        Spec.tires.aspect_ratio[I] = (Cockpit.WheelRadius * .01f * KartScale * Size - inch_to_m(Spec.tires.rim_size[I]) * .5f) /
                                    (Spec.tires.section_width[I] * .001f) * 100.f;
    }
    Car = MakeShared<FDrivingCar>(Spec);
    FindGroundOffset();
    FCarGround Ground{Rider->GetWorld(), Rider, TraceChannel};
    if (!Car->Chassis.place_on_ground(Ground, float(Spot.Y) * .01f, float(Spot.X) * .01f, float(Spot.Z) * .01f + 1.f,
                                     FMath::DegreesToRadians(Yaw.Yaw)))
    {
        Car.Reset();
        Hint = TEXT("No ground for the car");
        return false;
    }

    if (!BodyMesh && !BodyMeshPath.IsNull())
    {
        BodyMesh = Cast<UStaticMesh>(BodyMeshPath.TryLoad());
    }
    if (!WheelMesh && !WheelMeshPath.IsNull())
    {
        WheelMesh = Cast<UStaticMesh>(WheelMeshPath.TryLoad());
    }
    if (!SeatMesh && !SeatMeshPath.IsNull())
    {
        SeatMesh = Cast<UStaticMesh>(SeatMeshPath.TryLoad());
    }
    if (!SteeringMesh && !SteeringMeshPath.IsNull())
    {
        SteeringMesh = Cast<UStaticMesh>(SteeringMeshPath.TryLoad());
    }
    Body->SetStaticMesh(BodyMesh);
    Body->SetRelativeScale3D(FVector(KartScale));
    Body->SetRelativeLocation(FVector(0, 0, -GroundOffset));
    Body->SetVisibility(true, true);
    Seat->SetStaticMesh(SeatMesh);
    Seat->SetRelativeLocation(Cockpit.Seat);
    Seat->SetVisibility(true, true);
    for (int i = 0; i < 4; ++i)
    {
        Wheel[i]->SetStaticMesh(WheelMesh);
        Wheel[i]->SetRelativeLocation(Cockpit.WheelPositions[i]);
        Wheel[i]->SetRelativeRotation(FQuat::Identity);
        Wheel[i]->SetRelativeScale3D(FVector(i < 2 ? 1.f : 1.08f));
        Wheel[i]->SetVisibility(true, true);
        Spin[i] = 0.f;
    }
    Steering->SetStaticMesh(SteeringMesh);
    Steering->SetRelativeRotation(SteeringBase);
    Steering->SetVisibility(true, true);

    Rider->GetMesh()->SetVisibility(true, true);
    Rider->GetCapsuleComponent()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    bSavedUseControllerYaw = Rider->bUseControllerRotationYaw;
    Rider->bUseControllerRotationYaw = false;
    Rider->GetCharacterMovement()->StopMovementImmediately();
    Rider->GetCharacterMovement()->SetMovementMode(MOVE_None);

    bEquipped = true;
    bHasGround = false;
    LastGround = Spot;
    MoveInput = FVector2D::ZeroVector;
    bHandbrake = false;
    Hint = TEXT("Driving");
    UpdatePose(0.f);
    return true;
}

bool UDrivingComponent::Dismount()
{
    if (!Rider || !Car)
    {
        return false;
    }
    const FVector Forward = Rider->GetActorForwardVector();
    const FVector Right = Rider->GetActorRightVector();
    const FVector Base = Rider->GetActorLocation();
    const float Half = Rider->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
    for (const FVector& Candidate : {Base - Right * 150.f, Base + Right * 150.f, Base - Forward * 420.f})
    {
        FVector Ground;
        if (!GroundBelow(Candidate, 300.f, Ground))
        {
            continue;
        }
        FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingDismount), false, Rider);
        if (Rider->GetWorld()->OverlapBlockingTestByChannel(Ground + FVector(0, 0, Half + 2.f), FQuat::Identity,
                                                           TraceChannel, FCollisionShape::MakeCapsule(34.f, Half), Params))
        {
            continue;
        }
        EndDrive(Ground);
        return true;
    }
    Hint = TEXT("No room to step out");
    return false;
}

void UDrivingComponent::EndDrive(const FVector& GroundSpot)
{
    if (!Rider || !Car)
    {
        return;
    }
    const float Half = Rider->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
    Rider->SetActorLocation(GroundSpot + FVector(0, 0, Half + 2.f), false, nullptr, ETeleportType::TeleportPhysics);
    FinishDrive();
}

void UDrivingComponent::FinishDrive()
{
    if (!Rider || !Car)
    {
        return;
    }
    Rider->SetActorRotation(FRotator(0, Rider->GetActorRotation().Yaw, 0));
    Rider->GetMesh()->SetVisibility(true, true);
    Rider->GetCapsuleComponent()->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
    Rider->bUseControllerRotationYaw = bSavedUseControllerYaw;
    Rider->GetCharacterMovement()->SetMovementMode(MOVE_Walking);
    Body->SetVisibility(false, true);
    if (Seat) Seat->SetVisibility(false, true);
    for (int i = 0; i < 4; ++i) Wheel[i]->SetVisibility(false, true);
    if (Steering) Steering->SetVisibility(false, true);
    Car.Reset();
    bEquipped = false;
    Hint = TEXT("Parked");
}

bool UDrivingComponent::StandingRoom(const FVector& Ground) const
{
    if (!Rider || !Rider->GetWorld())
    {
        return false;
    }
    const float Half = Rider->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
    FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingDismount), false, Rider);
    return !Rider->GetWorld()->OverlapBlockingTestByChannel(Ground + FVector(0, 0, Half + 2.f), FQuat::Identity,
                                                           TraceChannel, FCollisionShape::MakeCapsule(34.f, Half), Params);
}

void UDrivingComponent::Recover()
{
    FVector Spot;
    if (bHasGround && GroundBelow(LastGround, 200.f, Spot) && StandingRoom(Spot))
    {
        EndDrive(Spot);
        Hint = TEXT("Recovered");
        return;
    }
    // No verified floor plus standing room: keep the capsule centre and let the game's fall/respawn handle it.
    FinishDrive();
    Hint = TEXT("Recovered without ground");
}

void UDrivingComponent::UpdatePose(float DeltaSeconds)
{
    if (!Rider || !Car)
    {
        return;
    }
    const FVector NewLocation = ToUE(Car->Chassis.position());
    const FQuat NewRotation = ToUE(Car->Chassis.orientation());
    const FVector OldLocation = Rider->GetActorLocation();

    FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingBody), false, Rider);
    const FCollisionShape Shape = FCollisionShape::MakeBox(Cockpit.BodyHalfExtents * (KartScale * .9f));
    FHitResult Hit;
    if (Rider->GetWorld()->SweepSingleByChannel(Hit, OldLocation, NewLocation, NewRotation, TraceChannel, Shape, Params))
    {
        if (FMath::Abs(Hit.ImpactNormal.Z) < .55f)
        {
            const Vec3 N = ToSimDir(Hit.ImpactNormal);
            Vec3 V = Car->Chassis.body.linear_velocity;
            const float Closing = dot(V, N);
            if (Closing < 0.f)
            {
                Car->Chassis.notify_wall_contact(ToSim(Hit.ImpactPoint), N, N * Closing, V);
                Car->Chassis.body.linear_velocity = V - N * Closing;
            }
            Car->Chassis.body.position = ToSim(OldLocation);
        }
    }
    Rider->SetActorLocationAndRotation(ToUE(Car->Chassis.position()), ToUE(Car->Chassis.orientation()).Rotator(), false,
                                       nullptr, ETeleportType::TeleportPhysics);
    float ContactY = 0.f;
    int Contacts = 0;
    for (int i = 0; i < 4; ++i)
    {
        const WheelState Wheel = Car->Chassis.wheel(i);
        if (Wheel.on_ground)
        {
            ContactY += Wheel.position.y;
            ++Contacts;
        }
    }
    if (Contacts > 0 && Body)
    {
        // The mesh's origin is the ground under the middle of the car: keep it on the contact patches as the
        // suspension settles, rather than at the free ride height it was placed at.
        const float Drop = (Car->Chassis.position().y - ContactY / float(Contacts)) * 100.f;
        Body->SetRelativeLocation(FVector(0, 0, -Drop));
        LastGround = ToUE(Car->Chassis.position()) - FVector(0, 0, Drop);
        bHasGround = true;
    }
    const float Steer = float(Car->Chassis.wheel(0).steer_angle);
    for (int i = 0; i < 4; ++i)
    {
        const WheelState State = Car->Chassis.wheel(i);
        const FVector Centre = ToUE(State.position) + NewRotation.RotateVector(FVector::UpVector) * (State.radius * 100.f);
        Wheel[i]->SetRelativeLocation(Body->GetComponentTransform().InverseTransformPosition(Centre));
        Spin[i] += float(State.angular_velocity) * DeltaSeconds;
        Wheel[i]->SetRelativeRotation(FQuat(FVector::UpVector, float(State.steer_angle)) *
                                      FQuat(FVector::RightVector, Spin[i]));
    }
    if (SteeringMesh)
    {
        Steering->SetRelativeRotation(SteeringBase * FQuat(FVector::ForwardVector, -Steer * 2.5f));
    }
}

void UDrivingComponent::SetInput(FVector2D Move)
{
    MoveInput = FVector2D(FMath::Clamp(Move.X, -1.f, 1.f), FMath::Clamp(Move.Y, -1.f, 1.f));
}

void UDrivingComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    if (!bEquipped || !Car || !Rider || !Rider->GetWorld())
    {
        return;
    }
    InputState Input;
    Input.steer = MoveInput.X;
    Input.throttle = FMath::Max(MoveInput.Y, 0.f);
    Input.brake = FMath::Max(-MoveInput.Y, 0.f);
    Input.handbrake = bHandbrake ? 1.f : 0.f;
    FCarGround Ground{Rider->GetWorld(), Rider, TraceChannel};
    Car->Accumulator = FMath::Min(Car->Accumulator + FMath::Min(DeltaTime, .25f), FIXED_STEP * 6.f);
    int Steps = 0;
    while (Car->Accumulator >= FIXED_STEP && Steps < 6)
    {
        Car->Chassis.step(FIXED_STEP, Input, Ground);
        Car->Accumulator -= FIXED_STEP;
        ++Steps;
    }
    if (Steps > 0)
    {
        UpdatePose(DeltaTime);
    }
    if (Car->Chassis.position().y < -20.0f)
    {
        Recover();
    }
}

float UDrivingComponent::GetSpeed() const
{
    return Car ? length(Car->Chassis.linear_velocity()) * 100.f : 0.f;
}

float UDrivingComponent::GetSpeedKph() const
{
    return GetSpeed() * .036f;
}

FTransform UDrivingComponent::GetCarTransform() const
{
    if (!Car)
    {
        return FTransform::Identity;
    }
    return FTransform(ToUE(Car->Chassis.orientation()), ToUE(Car->Chassis.position()));
}

FVector UDrivingComponent::PosePoint(const FVector& Local) const
{
    return Body ? Body->GetComponentTransform().TransformPosition(Local) : Local;
}

FVector UDrivingComponent::PoseDirection(const FVector& Local) const
{
    return Body ? Body->GetComponentTransform().TransformVectorNoScale(Local) : Local;
}

FVector UDrivingComponent::HandPoint(int32 Side) const
{
    const float Bar = Car ? -float(Car->Chassis.wheel(0).steer_angle) * 2.5f : 0.f;
    const float Sign = AtelierDrivingSide::Sign(Side);   // 9:15 (left) and 2:45 (right), just above horizontal
    const float Elev = FMath::DegreesToRadians(Cockpit.GripElevation);
    const FVector Rim(0, Sign * Cockpit.SteeringRadius * FMath::Cos(Elev), Cockpit.SteeringRadius * FMath::Sin(Elev));
    return Cockpit.Steering + SteeringBase.RotateVector(FQuat(FVector::ForwardVector, Bar).RotateVector(Rim));
}

FVector UDrivingComponent::GripForward(int32 Side) const
{
    (void)Side;
    return SteeringBase.RotateVector(FVector(1, 0, 0));
}

FVector UDrivingComponent::GripUp(int32 Side) const
{
    const float Bar = Car ? -float(Car->Chassis.wheel(0).steer_angle) * 2.5f : 0.f;
    const float Sign = AtelierDrivingSide::Sign(Side);
    const float Elev = FMath::DegreesToRadians(Cockpit.GripElevation);
    const FVector Radial(0, Sign * FMath::Cos(Elev), FMath::Sin(Elev));
    return SteeringBase.RotateVector(FQuat(FVector::ForwardVector, Bar).RotateVector(Radial));
}

FVector UDrivingComponent::GripAxis(int32 Side) const
{
    const float Bar = Car ? -float(Car->Chassis.wheel(0).steer_angle) * 2.5f : 0.f;
    const float Sign = AtelierDrivingSide::Sign(Side);
    const float Elev = FMath::DegreesToRadians(Cockpit.GripElevation);
    const FVector Tangent(0, -Sign * FMath::Sin(Elev), FMath::Cos(Elev));
    return SteeringBase.RotateVector(FQuat(FVector::ForwardVector, Bar).RotateVector(Tangent));
}


bool UDrivingComponent::AuthoredGripWorld(FName Bone, FTransform& Out) const
{
    const FTransform* Frame = AuthoredGrips.Find(Bone);
    if (!Frame || !Steering || !bEquipped) return false;
    Out = *Frame * Steering->GetComponentTransform();
    return true;
}


void UDrivingComponent::SetAuthoredFit(float Lean, float Height, float Tilt)
{
    if (bEquipped || !Steering) return;
    AuthoredLean = Lean;
    const float Angle = Cockpit.SteeringTilt + Tilt;
    if (!FMath::IsFinite(Angle) || Angle < 15.f || Angle > 75.f || !ColumnMesh || !SteeringColumn) return;
    FVector Hub = Cockpit.Steering + FVector(0., 0., Height);
    Hub.X = Cockpit.SteeringColumnBase.X - (Hub.Z - Cockpit.SteeringColumnBase.Z) / FMath::Tan(FMath::DegreesToRadians(Angle));
    SteeringBase = FQuat(FVector::RightVector, FMath::DegreesToRadians(Angle));
    Steering->SetRelativeRotation(SteeringBase);
    Steering->SetRelativeLocation(Hub);
    const FVector Shaft = Hub - Cockpit.SteeringColumnBase;
    const FVector Extent = ColumnMesh->GetBounds().BoxExtent;
    SteeringColumn->SetRelativeLocation((Hub + Cockpit.SteeringColumnBase) * .5f);
    SteeringColumn->SetRelativeRotation(FQuat::FindBetweenNormals(FVector::UpVector, Shaft.GetSafeNormal()));
    SteeringColumn->SetRelativeScale3D(FVector(1.9f / Extent.X, 1.9f / Extent.Y, Shaft.Size() / (Extent.Z * 2.f)));
}
