// The Belmonte train's sounds (the transport bank's train_* cues: assets/audio/transport/make.py TRAIN_SPEC, imported to
// /Game/Audio/Transport by unreal.sounds and loaded with TransportAudio.h's LoadTransportWave), played from
// the train's own motion: the service places every train from the shared clock on every machine, and the sound follows
// the same pure functions (BelmonteTrainRules::SoundMix, StopCues, FBelmonteTrainLine::Stands), so a host and its guests
// hear the train they see, accelerating and braking with it, without replicating anything more. Each sound comes from
// where it is made (service.json "sound", ABelmonteTrainService::SoundEmitters): the engine's from its chimney and
// cylinders, the roll and the clacks from every vehicle's wheels, the doors from each door.
#include "BelmonteTrainService.h"
#include "BelmonteTrainRules.h"
#include "TransportAudio.h"
#include "Components/AudioComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundAttenuation.h"
#include "Sound/SoundWave.h"
#include "Engine/World.h"

namespace
{
/** make.py's TRAIN_*: the roll recording's speed (m/s, pitch 1 there), the rail length (m, one clack per bogie per joint),
 *  the effort loop's exhaust beats per second at rate 1 (CHUFF_BEATS_PER_S) and the pass-by's loudest moment (PASS_PEAK_S). */
constexpr double RollSpeed = 22., RailLength = 25., ChuffLoopBeats = 9.449, PassPeak = 7.;
/** The doors close this long before a departure (s of the timetable). */
constexpr double DoorsLead = 4.;
/** Clacks and doors are played only within this distance of the listener (cm): they are short and local. */
constexpr double ClackReach = 12000.;
/** The roll loops that play: the wheels nearest the listener. */
constexpr int32 MaxWheelVoices = 8;
/** A pass-by: for a listener within PassSide cm of the line ahead of an engine running faster than PassSpeed m/s, once
 *  a passage (PassAgain s). */
constexpr double PassSide = 4000., PassSpeed = 12., PassAgain = 30.;
/** Inside a coach: sounds from elsewhere on the train are muffled through its body; its own wheels under the floor
 *  less so and quieter. */
constexpr float MuffledHz = 1200.f, FloorHz = 2500.f, FloorGain = .6f;

USoundWave* LoadTrainWave(const TCHAR* Cue, int32 Index = 1)
{
    return LoadTransportWave(FString::Printf(TEXT("%s_%02d"), Cue, Index));
}

/** Natural distance falloff, darker with distance (a passenger at the back hears the engine distant and muffled). */
USoundAttenuation* MakeAttenuation(UObject* Outer, float Inner, float Falloff, float FarHz)
{
    auto* Attenuation = NewObject<USoundAttenuation>(Outer);
    FSoundAttenuationSettings& A = Attenuation->Attenuation;
    A.bAttenuate = true; A.bSpatialize = true; A.AttenuationShape = EAttenuationShape::Sphere;
    A.AttenuationShapeExtents = FVector(Inner, 0.f, 0.f); A.FalloffDistance = Falloff;
    A.DistanceAlgorithm = EAttenuationDistanceModel::NaturalSound; A.dBAttenuationAtMax = -60.f;
    A.bAttenuateWithLPF = true; A.LPFRadiusMin = Inner; A.LPFRadiusMax = Inner + Falloff;
    A.LPFFrequencyAtMin = 20000.f; A.LPFFrequencyAtMax = FarHz;
    return Attenuation;
}

/** A loop at its mix volume and pitch: started when audible, stopped when silent. */
void Drive(UAudioComponent* Loop, float Volume, float Pitch, int32 Seed)
{
    if (!Loop) return;
    if (Volume > .01f)
    {
        if (!Loop->IsPlaying()) Loop->Play(FMath::Fmod(float(Seed) * 1.7f, 4.f));    // voices out of step
        Loop->SetVolumeMultiplier(Volume);
        Loop->SetPitchMultiplier(Pitch);
    }
    else if (Loop->IsPlaying()) Loop->Stop();
}

/** A one-shot that plays through a phase: started At s into it when it becomes audible (a late joiner hears it where
 *  everyone else does), followed in volume, stopped when silent. */
void DriveAt(UAudioComponent* Shot, float Volume, float Pitch, double At)
{
    if (!Shot) return;
    const USoundBase* Sound = Shot->Sound;
    if (Volume > .01f && Sound && At >= 0. && At < Sound->GetDuration())
    {
        if (!Shot->IsPlaying()) Shot->Play(float(At));
        Shot->SetVolumeMultiplier(Volume);
        Shot->SetPitchMultiplier(Pitch);
    }
    else if (Shot->IsPlaying() && Volume <= .01f) Shot->Stop();
}

const TCHAR* EmitterName(ETrainEmitter Kind)
{
    switch (Kind)
    {
    case ETrainEmitter::Chimney: return TEXT("chimney");
    case ETrainEmitter::Cylinder: return TEXT("cylinder");
    case ETrainEmitter::Door: return TEXT("door");
    default: return TEXT("wheel");
    }
}
}

void ABelmonteTrainService::LoadSounds()
{
    TrainStands.Reset();
    EngineVehicles.Reset();
    for (int32 Train = 0; Train < Line.Trains.Num(); ++Train)
    {
        TrainStands.Add(Line.Stands(Train));
        int32 Engine = Vehicles.IndexOfByPredicate([Train](const FVehicle& V) { return V.Train == Train && V.Id == TEXT("locomotive"); });
        if (Engine == INDEX_NONE) Engine = Vehicles.IndexOfByPredicate([Train](const FVehicle& V) { return V.Train == Train; });
        EngineVehicles.Add(Engine);
    }
    LastPass.Init(-1e9, Line.Trains.Num());
    if (IsRunningDedicatedServer() || !GetWorld()) return;
    // The voices are placed even where nothing is heard (a -nosound check still finds them where they belong).
    USoundWave* Roll = LoadTrainWave(TEXT("train_roll"));
    USoundWave* Idle = LoadTrainWave(TEXT("train_idle"));
    USoundWave* Start = LoadTrainWave(TEXT("train_start"));
    USoundWave* Effort = LoadTrainWave(TEXT("train_effort"));
    ClackSounds.Reset();
    while (USoundWave* Clack = LoadTrainWave(TEXT("train_clack"), ClackSounds.Num() + 1)) ClackSounds.Add(Clack);
    BrakeSound = LoadTrainWave(TEXT("train_brake"));
    DepartSound = LoadTrainWave(TEXT("train_depart"));
    DoorsSound = LoadTrainWave(TEXT("train_doors"));
    HissSound = LoadTrainWave(TEXT("train_hiss"));
    PassSound = LoadTrainWave(TEXT("train_pass"));
    // Wheels and doors are heard near them (about 70 m); the engine and its whistle across the station and beyond.
    RollAttenuation = MakeAttenuation(this, 600.f, 6500.f, 3000.f);
    SignalAttenuation = MakeAttenuation(this, 2500.f, 16000.f, 2500.f);
    auto Voice = [this](int32 Vehicle, const FVector& Local, USoundWave* Wave, const FString& Name, USoundAttenuation* Attenuation)
    {
        auto* L = NewObject<UAudioComponent>(this, *Name);
        L->SetupAttachment(Vehicles[Vehicle].Body);
        L->SetRelativeLocation(Local);
        L->bAutoActivate = false; L->bAllowSpatialization = true;
        L->AttenuationSettings = Attenuation;
        L->SetSound(Wave);
        L->RegisterComponent();
        return L;
    };
    RollLoops.Reset(); RollWheels.Reset(); LastWheels.Reset();
    for (int32 I = 0; I < Vehicles.Num(); ++I)
        for (int32 E = 0; E < Vehicles[I].Emitters.Num(); ++E)
            if (Vehicles[I].Emitters[E].Kind == ETrainEmitter::Wheel && Roll)
            {
                RollLoops.Add(Voice(I, Vehicles[I].Emitters[E].Local, Roll, FString::Printf(TEXT("TrainRoll_%s_%s_%s"),
                    *Line.Trains[Vehicles[I].Train].Name, *Vehicles[I].Id, *Vehicles[I].Emitters[E].Id), RollAttenuation));
                RollWheels.Add(FIntPoint(I, E));
                LastWheels.Add(TNumericLimits<double>::Max());
            }
    IdleLoops.Reset(); StartSounds.Reset(); EffortLoops.Reset();
    for (int32 Train = 0; Train < Line.Trains.Num(); ++Train)
    {
        const int32 Engine = EngineVehicles[Train];
        const FTrainEmitter* Chimney = Engine == INDEX_NONE ? nullptr : Vehicles[Engine].Emitters.FindByPredicate([](const FTrainEmitter& E) { return E.Kind == ETrainEmitter::Chimney; });
        if (Engine != INDEX_NONE && !Chimney) UE_LOG(LogTemp, Warning, TEXT("TRAIN SOUNDS %s: no chimney in the service data (re-stage it): the engine sounds from its centre"), *Line.Trains[Train].Name);
        const FVector At = Chimney ? Chimney->Local : FVector::ZeroVector;
        const FString Name = Line.Trains[Train].Name;
        IdleLoops.Add(Engine != INDEX_NONE && Idle ? Voice(Engine, At, Idle, TEXT("TrainIdle_") + Name, SignalAttenuation) : nullptr);
        StartSounds.Add(Engine != INDEX_NONE && Start ? Voice(Engine, At, Start, TEXT("TrainStart_") + Name, SignalAttenuation) : nullptr);
        EffortLoops.Add(Engine != INDEX_NONE && Effort ? Voice(Engine, At, Effort, TEXT("TrainEffort_") + Name, SignalAttenuation) : nullptr);
    }
    int32 Stands = 0, Doors = 0;
    for (const auto& S : TrainStands) Stands += S.Num();
    for (const FVehicle& V : Vehicles) for (const FTrainEmitter& E : V.Emitters) Doors += E.Kind == ETrainEmitter::Door;
    UE_LOG(LogTemp, Display, TEXT("TRAIN SOUNDS roll=%d idle=%d start=%d effort=%d clack=%d brake=%d depart=%d doors=%d hiss=%d pass=%d stands=%d wheels=%d door_emitters=%d"),
        Roll != nullptr, Idle != nullptr, Start != nullptr, Effort != nullptr, ClackSounds.Num(), BrakeSound != nullptr, DepartSound != nullptr,
        DoorsSound != nullptr, HissSound != nullptr, PassSound != nullptr, Stands, RollLoops.Num(), Doors);
}

void ABelmonteTrainService::UpdateSounds(double Time, float Dt)
{
    const double Previous = LastSoundTime;
    LastSoundTime = Time;
    const double Scale = FMath::Max(ClockScale(), 1e-3);
    FVector Ear = FVector::ZeroVector, Front, Right;
    const APlayerController* PC = GetWorld()->GetFirstPlayerController();
    if (PC) PC->GetAudioListenerPosition(Ear, Front, Right);
    const bool bEar = PC != nullptr;
    // The coach whose interior holds the listener: everything else on the train is heard through its body.
    ListenerVehicle = INDEX_NONE;
    for (int32 I = 0; bEar && I < Vehicles.Num() && ListenerVehicle == INDEX_NONE; ++I)
    {
        const FVector Local = Vehicles[I].Body->GetComponentTransform().InverseTransformPosition(Ear);
        for (const FInterior& Room : Vehicles[I].Interiors) if (Room.bCamera && Room.Box.IsInside(Local)) { ListenerVehicle = I; break; }
    }
    auto Muffle = [this](UAudioComponent* C, int32 Vehicle, bool bWheel) -> float
    {
        if (!C) return 1.f;
        const bool bInside = ListenerVehicle != INDEX_NONE;
        const bool bOwn = Vehicle == ListenerVehicle;
        const float Hz = !bInside ? 0.f : (bOwn ? (bWheel ? FloorHz : 0.f) : MuffledHz);
        // the component's own settings (for a sound started later) and the playing sound's
        C->bEnableLowPassFilter = Hz > 0.f;
        if (Hz > 0.f) C->LowPassFilterFrequency = Hz;
        C->SetLowPassFilterEnabled(Hz > 0.f);
        if (Hz > 0.f) C->SetLowPassFilterFrequency(Hz);
        return bInside && bOwn && bWheel ? FloorGain : 1.f;
    };
    auto Emitters = [this](int32 Vehicle, ETrainEmitter Kind)
    {
        TArray<FVector, TInlineAllocator<4>> Out;
        if (Vehicles.IsValidIndex(Vehicle)) for (const FTrainEmitter& E : Vehicles[Vehicle].Emitters) if (E.Kind == Kind) Out.Add(E.Local);
        return Out;
    };
    // A one-shot hung on a vehicle at a point of it (it moves with the train), muffled like the loops.
    auto Shot = [&](USoundWave* Wave, int32 Vehicle, const FVector& Local, float Volume, float Pitch, USoundAttenuation* Attenuation, bool bWheel)
    {
        if (!Wave || !Vehicles.IsValidIndex(Vehicle) || !Attenuation) return;
        UAudioComponent* C = UGameplayStatics::SpawnSoundAttached(Wave, Vehicles[Vehicle].Body, NAME_None, Local, EAttachLocation::KeepRelativeOffset,
            true, 1.f, Pitch, 0.f, Attenuation);
        if (C) C->SetVolumeMultiplier(Volume * Muffle(C, Vehicle, bWheel));
    };
    auto Engine = [this](int32 Train) { return EngineVehicles.IsValidIndex(Train) ? EngineVehicles[Train] : INDEX_NONE; };
    auto EnginePoint = [&](int32 Train, ETrainEmitter Kind, int32 Nth)
    {
        const auto Points = Emitters(Engine(Train), Kind);
        return Points.IsValidIndex(Nth) ? Points[Nth] : (Points.Num() ? Points.Last() : FVector::ZeroVector);
    };
    // The cues of each stand: the brakes from the deceleration to the stop (at the coupled wheels) and the blow-off at
    // the stop (from the cylinders); the doors closing DoorsLead s before the departure (each door near the listener)
    // and the whistle (at the chimney) as it moves off.
    if (Previous >= 0.)
        for (int32 Train = 0; Train < TrainStands.Num(); ++Train)
        {
            const int32 E = Engine(Train);
            if (E == INDEX_NONE) continue;
            for (const FBelmonteTrainStand& Stand : TrainStands[Train])
            {
                const BelmonteTrainRules::FTrainStopCues Cues = BelmonteTrainRules::StopCues(Stand.BrakeStart, Stand.Arrive, BrakeSound ? BrakeSound->Duration : 0., Scale);
                if (BelmonteTrainRules::EventDue(Cues.Brake, Previous, Time, Line.Cycle))
                { Shot(BrakeSound, E, EnginePoint(Train, ETrainEmitter::Wheel, 1), 1.f, Cues.Pitch, SignalAttenuation, true); ++SoundEvents[0]; }
                if (BelmonteTrainRules::EventDue(Cues.Blast, Previous, Time, Line.Cycle))
                {
                    const auto Cylinders = Emitters(E, ETrainEmitter::Cylinder);
                    for (const FVector& At : Cylinders) Shot(HissSound, E, At, .71f, 1.f, SignalAttenuation, false);
                    if (Cylinders.IsEmpty()) Shot(HissSound, E, FVector::ZeroVector, 1.f, 1.f, SignalAttenuation, false);
                    ++SoundEvents[4];
                }
                if (BelmonteTrainRules::EventDue(Stand.Depart, Previous, Time, Line.Cycle))
                { Shot(DepartSound, E, EnginePoint(Train, ETrainEmitter::Chimney, 0), 1.f, 1.f, SignalAttenuation, false); ++SoundEvents[1]; }
                if (BelmonteTrainRules::EventDue(Stand.Depart - DoorsLead, Previous, Time, Line.Cycle))
                {
                    ++SoundEvents[3];
                    for (int32 I = 0; I < Vehicles.Num() && bEar; ++I)
                        if (Vehicles[I].Train == Train)
                            for (const FVector& Door : Emitters(I, ETrainEmitter::Door))
                                if (FVector::DistSquared(Ear, Vehicles[I].Body->GetComponentTransform().TransformPosition(Door)) < FMath::Square(ClackReach))
                                    Shot(DoorsSound, I, Door, 1.f, FMath::FRandRange(.97f, 1.03f), RollAttenuation, false);
                }
            }
        }
    // The continuous layers, from each train's speed and acceleration as heard (service rates times the clock's scale).
    TArray<BelmonteTrainRules::FTrainSoundMix, TInlineAllocator<4>> Mixes;
    for (int32 Train = 0; Train < Line.Trains.Num(); ++Train)
    {
        const double Signed = Line.Speed(Train, Time);
        const double Speed = FMath::Abs(Signed) * Scale;
        const double Accel = (FMath::Abs(Line.Speed(Train, Time + .5)) - FMath::Abs(Line.Speed(Train, Time - .5))) * Scale * Scale;
        const BelmonteTrainRules::FTrainStandClock Stand = TrainStands.IsValidIndex(Train)
            ? BelmonteTrainRules::StandClock(TrainStands[Train], Time, Line.Cycle, Scale) : BelmonteTrainRules::FTrainStandClock();
        UAudioComponent* Start = StartSounds.IsValidIndex(Train) ? StartSounds[Train].Get() : nullptr;
        const double StartSeconds = Start && Start->Sound ? Start->Sound->GetDuration() : 0.;
        Mixes.Add(BelmonteTrainRules::SoundMix(Speed, Accel, RollSpeed, Stand, StartSeconds, ChuffLoopBeats));
        const BelmonteTrainRules::FTrainSoundMix& M = Mixes.Last();
        UAudioComponent* Idle = IdleLoops.IsValidIndex(Train) ? IdleLoops[Train].Get() : nullptr;
        UAudioComponent* Effort = EffortLoops.IsValidIndex(Train) ? EffortLoops[Train].Get() : nullptr;
        const int32 E = Engine(Train);
        Drive(Idle, M.Idle * Muffle(Idle, E, false), 1.f, Train);
        DriveAt(Start, M.Start * Muffle(Start, E, false), 1.f, Stand.SinceStop >= 0. ? -1. : Stand.SinceDepart);
        Drive(Effort, M.Effort * Muffle(Effort, E, false), M.ChuffRate, Train);
        // A pass-by for a listener beside the line ahead of an engine at speed (not riding it): started so its loudest
        // moment comes as the engine draws level, from the engine.
        if (PassSound && bEar && Vehicles.IsValidIndex(E) && Speed > PassSpeed && LastPass.IsValidIndex(Train) && (ListenerVehicle == INDEX_NONE || Vehicles[ListenerVehicle].Train != Train)
            && GetWorld()->GetTimeSeconds() - LastPass[Train] > PassAgain)
        {
            const FTransform Body = Vehicles[E].Body->GetComponentTransform();
            const FVector Ahead = Body.GetUnitAxis(EAxis::X) * (Signed < 0. ? -1. : 1.);
            const FVector Rel = Ear - Body.TransformPosition(EnginePoint(Train, ETrainEmitter::Chimney, 0));
            const double Along = FVector::DotProduct(Rel, Ahead), Side = (Rel - Along * Ahead).Size();
            const double Until = Along / (Speed * 100.);
            if (Side < PassSide && Until > 0. && Until <= PassPeak)
            {
                LastPass[Train] = GetWorld()->GetTimeSeconds();
                UAudioComponent* C = UGameplayStatics::SpawnSoundAttached(PassSound, Vehicles[E].Body, NAME_None, EnginePoint(Train, ETrainEmitter::Chimney, 0),
                    EAttachLocation::KeepRelativeOffset, true, 1.f, 1.f, float(PassPeak - Until), SignalAttenuation);
                if (C) Muffle(C, E, false);
                ++SoundEvents[5];
            }
        }
    }
    LastMixes.Reset(); LastMixes.Append(Mixes);
    // The roll at the wheels nearest the listener; a clack for each joint a wheel set passed this frame, near it.
    TArray<double> Distance; Distance.SetNumUninitialized(RollWheels.Num());
    TArray<int32> Order;
    for (int32 W = 0; W < RollWheels.Num(); ++W)
    {
        const FVehicle& V = Vehicles[RollWheels[W].X];
        Distance[W] = FVector::Dist(Ear, V.Body->GetComponentTransform().TransformPosition(V.Emitters[RollWheels[W].Y].Local));
        Order.Add(W);
    }
    Order.Sort([&Distance](int32 A, int32 B) { return Distance[A] < Distance[B]; });
    TBitArray<> Near(false, RollWheels.Num());
    for (int32 K = 0; K < FMath::Min(MaxWheelVoices, Order.Num()); ++K) Near[Order[K]] = true;
    for (int32 W = 0; W < RollWheels.Num(); ++W)
    {
        const int32 I = RollWheels[W].X;
        const FVehicle& V = Vehicles[I];
        if (!Mixes.IsValidIndex(V.Train)) continue;
        const BelmonteTrainRules::FTrainSoundMix& M = Mixes[V.Train];
        UAudioComponent* Loop = RollLoops[W].Get();
        Drive(Loop, Near[W] && bEar ? M.Roll * .7f * Muffle(Loop, I, true) : 0.f, M.RollPitch, W);
        const double Wheel = Line.Chainage(V.Train, Time) + V.Offset + V.Emitters[RollWheels[W].Y].Local.X / 100.;
        const double Last = LastWheels[W];
        LastWheels[W] = Wheel;
        if (Last == TNumericLimits<double>::Max() || M.Clack <= .01f) continue;
        const int32 Joints = BelmonteTrainRules::JointsCrossed(Last, Wheel, RailLength);
        SoundEvents[2] += Joints;
        if (Joints && Near[W] && Distance[W] < ClackReach && ClackSounds.Num())
            Shot(ClackSounds[FMath::RandRange(0, ClackSounds.Num() - 1)], I, V.Emitters[RollWheels[W].Y].Local,
                M.Clack * FMath::Pow(10.f, FMath::FRandRange(-2.f, 2.f) / 20.f), M.ClackPitch * FMath::FRandRange(.96f, 1.04f), RollAttenuation, true);
    }
}

TArray<FTrainSoundVoice> ABelmonteTrainService::SoundVoices(const FVector& Ear) const
{
    TArray<FTrainSoundVoice> Out;
    auto Add = [&](const UAudioComponent* C, int32 Vehicle, ETrainEmitter Kind)
    {
        if (!C || !Vehicles.IsValidIndex(Vehicle)) return;
        FTrainSoundVoice& V = Out.AddDefaulted_GetRef();
        V.Name = C->GetName(); V.Vehicle = Vehicles[Vehicle].Id; V.Train = Vehicles[Vehicle].Train; V.Kind = Kind;
        V.Parent = C->GetAttachParent(); V.Body = Vehicles[Vehicle].Body; V.Local = C->GetRelativeLocation();
        V.bPlaying = C->IsPlaying(); V.Volume = V.bPlaying ? C->VolumeMultiplier : 0.f;
        V.Distance = FVector::Dist(Ear, C->GetComponentLocation()) / 100.;
        const USoundAttenuation* A = C->AttenuationSettings;
        V.Attenuated = V.Volume * (A ? A->Attenuation.Evaluate(C->GetComponentTransform(), Ear, 1.f) : 1.f);
        V.LowPass = C->bEnableLowPassFilter ? C->LowPassFilterFrequency : 0.f;
    };
    for (int32 Train = 0; Train < EngineVehicles.Num(); ++Train)
    {
        const int32 E = EngineVehicles[Train];
        if (IdleLoops.IsValidIndex(Train)) Add(IdleLoops[Train], E, ETrainEmitter::Chimney);
        if (StartSounds.IsValidIndex(Train)) Add(StartSounds[Train], E, ETrainEmitter::Chimney);
        if (EffortLoops.IsValidIndex(Train)) Add(EffortLoops[Train], E, ETrainEmitter::Chimney);
    }
    for (int32 W = 0; W < RollLoops.Num() && W < RollWheels.Num(); ++W) Add(RollLoops[W], RollWheels[W].X, ETrainEmitter::Wheel);
    return Out;
}

FString ABelmonteTrainService::SoundVoicesJson(const FVector& Ear) const
{
    // The engine's voices and the wheels that play, nearest first: where each is, how far, how loud it arrives.
    TArray<FTrainSoundVoice> Voices = SoundVoices(Ear);
    Voices.RemoveAll([](const FTrainSoundVoice& V) { return V.Kind == ETrainEmitter::Wheel && !V.bPlaying; });
    Voices.Sort([](const FTrainSoundVoice& A, const FTrainSoundVoice& B) { return A.Distance < B.Distance; });
    FString Out;
    for (const FTrainSoundVoice& V : Voices)
        Out += FString::Printf(TEXT("%s{\"name\":\"%s\",\"vehicle\":\"%s\",\"train\":%d,\"kind\":\"%s\",\"attached\":%s,\"local\":[%.0f,%.0f,%.0f],\"m\":%.1f,\"volume\":%.3f,\"heard\":%.4f,\"lpf\":%.0f}"),
            Out.IsEmpty() ? TEXT("") : TEXT(","), *V.Name, *V.Vehicle, V.Train, EmitterName(V.Kind), V.Parent && V.Parent == V.Body ? TEXT("true") : TEXT("false"),
            V.Local.X, V.Local.Y, V.Local.Z, V.Distance, V.Volume, V.Attenuated, V.LowPass);
    return Out;
}
