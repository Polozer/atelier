#include "DrivingComponent.h"

#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Simulation/SimulationKei.h"
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
}

void UDrivingComponent::SetBodyMesh(const FSoftObjectPath& Mesh)
{
    BodyMeshPath = Mesh;
    BodyMesh = Cast<UStaticMesh>(Mesh.TryLoad());
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
        Dismount();
        return true;
    }
    return Summon();
}

void UDrivingComponent::StowImmediately()
{
    if (!bEquipped)
    {
        return;
    }
    Dismount();
}

FVector UDrivingComponent::GroundBelow(const FVector& At, float Reach) const
{
    if (!Rider || !Rider->GetWorld())
    {
        return At;
    }
    FHitResult Hit;
    FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingPlace), false, Rider);
    const FVector From = At + FVector(0, 0, Reach * .5f);
    if (Rider->GetWorld()->LineTraceSingleByChannel(Hit, From, From - FVector(0, 0, Reach * 1.5f), TraceChannel, Params))
    {
        return Hit.ImpactPoint;
    }
    return At - FVector(0, 0, Reach);
}

bool UDrivingComponent::FreeAt(const FVector& At, const FQuat& Rotation) const
{
    if (!Rider || !Rider->GetWorld())
    {
        return false;
    }
    FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingPlace), false, Rider);
    const FCollisionShape Shape = FCollisionShape::MakeBox(FVector(169.f, 73.f, 70.f) * .88f);
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
    if (!Rider || !Rider->GetWorld() || !Body)
    {
        Hint = TEXT("The car is not ready");
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
        const FVector Ground = GroundBelow(Candidate, 320.f);
        if (FreeAt(Ground + FVector(0, 0, 75.f), Yaw.Quaternion()))
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

    Car = MakeShared<FDrivingCar>(kei_spec());
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
    if (BodyMesh)
    {
        Body->SetStaticMesh(BodyMesh);
        Body->SetRelativeScale3D(FVector::OneVector);
        BodyLift = 0.f;
        Body->SetRelativeLocation(FVector(0, 0, -GroundOffset));
    }
    else
    {
        if (UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube")))
        {
            Body->SetStaticMesh(Cube);
            Body->SetRelativeScale3D(FVector(3.39f, 1.47f, 1.44f));
            BodyLift = 72.f;
            Body->SetRelativeLocation(FVector(0, 0, -GroundOffset + 72.f));
        }
    }
    Body->SetVisibility(true, true);

    Rider->GetMesh()->SetVisibility(false, true);
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
    UpdatePose();
    return true;
}

void UDrivingComponent::Dismount()
{
    if (!Rider || !Car)
    {
        return;
    }
    const FVector Forward = Rider->GetActorForwardVector();
    const FVector Right = Rider->GetActorRightVector();
    const FVector Base = Rider->GetActorLocation();
    const float Half = Rider->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
    FVector Exit = Base - Right * 150.f;
    for (const FVector& Candidate : {Base - Right * 150.f, Base + Right * 150.f, Base - Forward * 420.f})
    {
        const FVector Ground = GroundBelow(Candidate, 300.f);
        FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingDismount), false, Rider);
        if (!Rider->GetWorld()->OverlapBlockingTestByChannel(Ground + FVector(0, 0, Half + 2.f), FQuat::Identity,
                                                            TraceChannel, FCollisionShape::MakeCapsule(34.f, Half), Params))
        {
            Exit = Ground;
            break;
        }
    }
    EndDrive(Exit);
}

void UDrivingComponent::EndDrive(const FVector& GroundSpot)
{
    if (!Rider || !Car)
    {
        return;
    }
    const float Half = Rider->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
    Rider->SetActorLocation(GroundSpot + FVector(0, 0, Half + 2.f), false, nullptr, ETeleportType::TeleportPhysics);
    Rider->SetActorRotation(FRotator(0, Rider->GetActorRotation().Yaw, 0));
    Rider->GetMesh()->SetVisibility(true, true);
    Rider->GetCapsuleComponent()->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
    Rider->bUseControllerRotationYaw = bSavedUseControllerYaw;
    Rider->GetCharacterMovement()->SetMovementMode(MOVE_Walking);
    Body->SetVisibility(false, true);
    Car.Reset();
    bEquipped = false;
    Hint = TEXT("Parked");
}

void UDrivingComponent::Recover()
{
    const FVector Spot = bHasGround ? LastGround : Rider->GetActorLocation() - FVector(0, 0, 200.f);
    EndDrive(Spot);
    Hint = TEXT("Recovered");
}

void UDrivingComponent::UpdatePose()
{
    if (!Rider || !Car)
    {
        return;
    }
    const FVector NewLocation = ToUE(Car->Chassis.position());
    const FQuat NewRotation = ToUE(Car->Chassis.orientation());
    const FVector OldLocation = Rider->GetActorLocation();

    FCollisionQueryParams Params(SCENE_QUERY_STAT(DrivingBody), false, Rider);
    const FCollisionShape Shape = FCollisionShape::MakeBox(FVector(169.f, 73.f, 70.f) * .9f);
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
        Body->SetRelativeLocation(FVector(0, 0, -Drop + BodyLift));
        LastGround = ToUE(Car->Chassis.position()) - FVector(0, 0, Drop);
        bHasGround = true;
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
        UpdatePose();
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
