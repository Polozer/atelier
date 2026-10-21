#pragma once
#include "CoreMinimal.h"

/**
 * Pure Belmonte train passenger admission, intruder detection, and safe recovery rules.
 * Tested in BelmonteTrainServiceTests.cpp.
 */
namespace BelmonteTrainRules
{
/** The HUD line when a vehicle is refused on the train. */
inline const TCHAR* Refusal() { return TEXT("Pas à bord du train"); }

/** Taking out the skateboard, the bike, the horse or the sailboat: never aboard, seated or while stepping through a
 *  door (bTrainAction). Putting one away is always allowed. */
inline bool MayTakeOutVehicle(bool bAboard, bool bTrainAction) { return !bAboard && !bTrainAction; }

/** A vehicle's envelope (its exterior box, vehicle cm) holds the feet (vehicle cm): inside the coach, on the tender's
 *  load, on a step or up to RoofMargin above the roof. */
inline bool InEnvelope(const FBox& Exterior, const FVector& LocalFeet, double RoofMargin = 60.)
{
    return LocalFeet.X >= Exterior.Min.X && LocalFeet.X <= Exterior.Max.X && LocalFeet.Y >= Exterior.Min.Y &&
        LocalFeet.Y <= Exterior.Max.Y && LocalFeet.Z >= Exterior.Min.Z && LocalFeet.Z <= Exterior.Max.Z + RoofMargin;
}

/**
 * On the train for the vehicle rule, ticket or not (walked in at a platform, ridden in, jumped onto a roof or into the
 * tender): standing on any of its vehicles (bOnFloor), or within a vehicle's envelope while it stands or the player
 * moves with it (bWithCoach, MovesWithCoach). A bystander the running train sweeps through is not on it. There no
 * vehicle comes out and an active one is put away (AWandererCharacter::IsOnTrain, StowVehicleOnTrain).
 */
inline bool OnTrainVehicle(bool bOnFloor, bool bInEnvelope, bool bCoachMoving, bool bWithCoach)
{
    return bOnFloor || (bInEnvelope && (!bCoachMoving || bWithCoach));
}

/**
 * Admission: the ticket the boarding walk gives (Monter at a station door), the one way to be carried as a passenger.
 * Owned by the host (offline: the game); clients take it from the replicated passenger list.
 *
 * It holds through the door walk and the steps (bHeld), seated (bHeld), standing up again, crossing a gangway or a
 * vestibule outside the rooms (bOnTrain: still inside a room with the gangway margin, or standing on a vehicle of the
 * train), and the train's travel. It ends on the walk down (Revoke), a cancel (a teleport, a respawn, the map's
 * travel: Revoke), or once the rider has been off the train for Grace seconds (walked out of an open door). A pawn
 * replacement carries it to the new pawn (MoveRider); a disconnected player's ticket goes with them (DropVanished).
 */
struct FAdmission
{
    static constexpr float Grace = 1.5f;
    bool bAdmitted = false;
    /** Seconds off the train since the rider was last on it. */
    float Outside = 0.f;

    void Admit() { bAdmitted = true; Outside = 0.f; }
    void Revoke() { bAdmitted = false; Outside = 0.f; }
    /** Each frame. bMayRevoke: the host or offline (a client only follows the host). Returns true when the ticket lapsed
     *  this frame. */
    bool Update(bool bOnTrain, bool bHeld, float Dt, bool bMayRevoke)
    {
        if (!bAdmitted) return false;
        if (bOnTrain || bHeld) { Outside = 0.f; return false; }
        Outside += Dt;
        if (Outside < Grace || !bMayRevoke) return false;
        Revoke();
        return true;
    }
    /** Still carried by the coach it was last in: admitted, and on the train or within the grace. */
    bool Carries() const { return bAdmitted && Outside < Grace; }
};

/** Moving with the coach, from the rider's speed in the coach's frame (cm/s) and the coach's own speed (cm/s): a person
 *  inside a running coach keeps their own small speed in its frame, while a bystander the coach sweeps past (a platform,
 *  a clipped hillside) moves through its frame at the coach's speed. A standing coach tells nothing (false). */
inline bool MovesWithCoach(double RelativeSpeed, double CoachSpeed)
{
    return CoachSpeed > 100. && RelativeSpeed < .5 * CoachSpeed;
}

/**
 * A player inside a coach's interior rooms without the ticket (on a vehicle through an open door, a jump, the
 * paraglider, a dash) is put back outside once the coach runs or is about to leave (bMovingOrDeparting: doors locked).
 * Only someone actually riding it counts (bWithCoach: standing on its floor, or MovesWithCoach): a bystander the coach
 * merely sweeps through stays where they are. A passenger, a seated player or one stepping through a door never.
 */
inline bool MustEject(bool bInsideCoach, bool bAdmitted, bool bBoarding, bool bSeated, bool bWithCoach, bool bMovingOrDeparting)
{
    return bInsideCoach && !bAdmitted && !bBoarding && !bSeated && bWithCoach && bMovingOrDeparting;
}

/**
 * Where an ejected player is set down: candidates in this order, each accepted only after AcceptStand.
 * - Platform: the station platform beside the coach (the platform side, at the player, then the station's arrival
 *   point), when the coach stands within a platform.
 * - DoorSide: beside the coach at the player and at its doors, the nearer side first.
 * - LastSafe: where the player last stood on walkable ground off the train (often the platform they left).
 * - TrainLastSafe: a door-side point recorded earlier while the train ran in the open.
 * - NextStation: the station the train runs to, then the others.
 * In a tunnel or on a viaduct (bEnclosed) the points beside the coach are never used.
 */
enum class ERecovery : uint8 { Platform, DoorSide, LastSafe, TrainLastSafe, NextStation };

inline TArray<ERecovery, TInlineAllocator<5>> RecoveryOrder(bool bAtPlatform, bool bEnclosed)
{
    if (bEnclosed) return {ERecovery::LastSafe, ERecovery::TrainLastSafe, ERecovery::NextStation};
    if (bAtPlatform) return {ERecovery::Platform, ERecovery::DoorSide, ERecovery::LastSafe, ERecovery::TrainLastSafe, ERecovery::NextStation};
    return {ERecovery::DoorSide, ERecovery::LastSafe, ERecovery::TrainLastSafe, ERecovery::NextStation};
}

/** What the world says about one candidate (BelmonteTrainRecovery::Probe). */
struct FStandProbe
{
    /** The first surface met from above: found, part of the train, its normal's z, its height off the expected z (cm). */
    bool bGround = false, bGroundIsTrain = false;
    double GroundNormalZ = 0., GroundOff = 0.;
    /** The standing capsule (a step above that ground) overlaps nothing. */
    bool bClear = false;
    /** The capsule swept down from there lands on a floor: found, part of the train, its normal's z. */
    bool bFloor = false, bFloorIsTrain = false;
    double FloorNormalZ = 0.;
};

/** A destination is safe only on walkable ground that is not the train, near the height expected, with room to stand:
 *  a height trace alone is never enough (a viaduct's deck edge, a tunnel's bore, a wall beside the point). */
inline bool AcceptStand(const FStandProbe& P, double WalkableZ, double MaxOff)
{
    return P.bGround && !P.bGroundIsTrain && P.GroundNormalZ >= WalkableZ && FMath::Abs(P.GroundOff) <= MaxOff &&
        P.bClear && P.bFloor && !P.bFloorIsTrain && P.FloorNormalZ >= WalkableZ;
}

/** The station a train heading Speed (m/s, + up the chainage) at chainage At reaches next; standing, the nearest.
 *  Chainages in any order; INDEX_NONE when there is none. */
inline int32 NextStop(const TArray<double>& Stations, double At, double Speed)
{
    int32 Best = INDEX_NONE;
    for (int32 I = 0; I < Stations.Num(); ++I)
    {
        const double S = Stations[I];
        const bool bAhead = Speed > .1 ? S >= At : Speed < -.1 ? S <= At : true;
        if (!bAhead) continue;
        if (Best == INDEX_NONE || FMath::Abs(S - At) < FMath::Abs(Stations[Best] - At)) Best = I;
    }
    // Past the last stop in that direction (a terminus overrun): the nearest one.
    if (Best == INDEX_NONE && FMath::Abs(Speed) > .1) return NextStop(Stations, At, 0.);
    return Best;
}

/** Pawn replacement: the From rider's entry (ticket, seat, walk, last safe ground) moves to To. An entry To already had
 *  (made the frame it spawned) is released and dropped first, so no lookup finds a ticketless duplicate. Riders have a
 *  `Character` with Get(). Returns the moved entry's index, or INDEX_NONE when From has none. */
template<typename TRider, typename TPtr, typename FRelease>
int32 MoveRider(TArray<TRider>& Riders, TPtr From, TPtr To, FRelease&& Release)
{
    int32 FromIndex = Riders.IndexOfByPredicate([From](const TRider& R) { return R.Character.Get() == From; });
    if (FromIndex == INDEX_NONE || !To || From == To) return INDEX_NONE;
    for (int32 I = Riders.Num() - 1; I >= 0; --I)
        if (I != FromIndex && Riders[I].Character.Get() == To)
        {
            Release(Riders[I]);
            Riders.RemoveAt(I);
            if (I < FromIndex) --FromIndex;
        }
    Riders[FromIndex].Character = To;
    return FromIndex;
}

/** A disconnected (destroyed) player's entry: released (its seat, the door it held open) and dropped with its ticket.
 *  Returns how many were dropped. */
template<typename TRider, typename FRelease>
int32 DropVanished(TArray<TRider>& Riders, FRelease&& Release)
{
    int32 Dropped = 0;
    for (int32 I = Riders.Num() - 1; I >= 0; --I)
        if (!Riders[I].Character.Get()) { Release(Riders[I]); Riders.RemoveAt(I); ++Dropped; }
    return Dropped;
}

/** A seated passenger's view follows the coach: the yaw the coach turned since last frame (degrees, -180..180), added
 *  to the passenger's control rotation, so the view they chose stays fixed in the coach (looking out of a window keeps
 *  looking out of that window) instead of swinging across it as the line curves. */
inline double CarriageTurn(double PreviousYaw, double Yaw)
{
    return FRotator::NormalizeAxis(Yaw - PreviousYaw);
}

/**
 * The aisle beside a seat, in the vehicle's frame (cm), from the seats of the seat's room alone: along each axis the
 * distinct seat coordinates leave gaps; the widest gap is the free floor between the seat rows (a saloon's central
 * aisle between the benches, a restaurant's between the tables, a compartment's floor between its facing sofas). The
 * seat is moved across onto that gap's middle (of equal gaps, the nearest). bFound is false when the room's seats
 * leave no gap (a single seat): the caller then steps off the seat's front.
 */
inline FVector2D AislePoint(const FVector2D& Seat, const TArray<FVector2D>& RoomSeats, bool& bFound)
{
    bFound = false;
    FVector2D Best = Seat;
    double BestGap = 0.;
    for (int32 Axis = 0; Axis < 2; ++Axis)
    {
        TArray<double> Values;
        for (const FVector2D& P : RoomSeats) Values.Add(Axis ? P.Y : P.X);
        Values.Sort();
        const double Here = Axis ? Seat.Y : Seat.X;
        double AxisGap = 0., AxisMid = Here;
        for (int32 I = 1; I < Values.Num(); ++I)
        {
            const double Gap = Values[I] - Values[I - 1], Mid = .5 * (Values[I] + Values[I - 1]);
            const bool bWider = Gap > AxisGap + 1.;
            const bool bTieNearer = FMath::Abs(Gap - AxisGap) <= 1. && FMath::Abs(Mid - Here) < FMath::Abs(AxisMid - Here);
            if (bWider || bTieNearer) { AxisGap = FMath::Max(AxisGap, Gap); AxisMid = Mid; }
        }
        if (AxisGap > BestGap + 1.)
        {
            BestGap = AxisGap; bFound = true;
            Best = Axis ? FVector2D(Seat.X, AxisMid) : FVector2D(AxisMid, Seat.Y);
        }
    }
    return Best;
}

/** The seats (x/y) of the room holding seat Index: the smallest of Rooms (a saloon, a compartment; not the whole body)
 *  whose plan holds it; all of them when no room does. */
inline TArray<FVector2D> RoomSeats(const TArray<FBox>& Rooms, const TArray<FVector2D>& Seats, int32 Index)
{
    TArray<FVector2D> Out;
    if (!Seats.IsValidIndex(Index)) return Out;
    auto Plan = [](const FBox& B) { return FBox2D(FVector2D(B.Min), FVector2D(B.Max)); };
    const FBox* Room = nullptr;
    for (const FBox& B : Rooms)
        if (Plan(B).IsInside(Seats[Index]) && (!Room || Plan(B).GetArea() < Plan(*Room).GetArea())) Room = &B;
    for (const FVector2D& S : Seats) if (!Room || Plan(*Room).IsInside(S)) Out.Add(S);
    return Out;
}

/**
 * Where a passenger stands up from a seat, in the vehicle's frame (cm, X/Y; the caller sets the floor height): the aisle
 * beside the seat (AislePoint) when its standing capsule is clear (Blocked: true where it overlaps the coach or
 * someone), else further along that aisle (up to MaxSlide cm either way, nearest first), else a step off the seat's
 * front (Forward: the seat's facing, Step cm), else the aisle point anyway. One rule for every seat: benches facing
 * across a table, banquettes, armchairs and compartment sofas.
 */
template<typename FBlocked>
FVector2D StandUpPoint(const FVector2D& Seat, const FVector2D& Forward, const TArray<FVector2D>& RoomSeats, FBlocked&& Blocked,
    double Step = 55., double SlideStep = 20., double MaxSlide = 120.)
{
    bool bAisle = false;
    const FVector2D Aisle = AislePoint(Seat, RoomSeats, bAisle);
    const FVector2D Front = Seat + Forward.GetSafeNormal() * Step;
    if (!bAisle) return Front;
    if (!Blocked(Aisle)) return Aisle;
    // Along the aisle: the axis the seat was not moved across.
    const FVector2D Along = FMath::Abs(Aisle.X - Seat.X) > FMath::Abs(Aisle.Y - Seat.Y) ? FVector2D(0., 1.) : FVector2D(1., 0.);
    for (double D = SlideStep; D <= MaxSlide + .5; D += SlideStep)
        for (const double Sign : {1., -1.})
            if (!Blocked(Aisle + Along * D * Sign)) return Aisle + Along * D * Sign;
    if (!Blocked(Front)) return Front;
    return Aisle;
}

/** One of a train's sound events (an arrival's brakes, a departure signal) at service time Event (repeating every Cycle
 *  seconds) falls in (Previous, Now]: the shared clock moved forward by less than MaxStep this frame (a dev jump or a
 *  join never replays the events it skipped). */
inline bool EventDue(double Event, double Previous, double Now, double Cycle, double MaxStep = 2.)
{
    if (Cycle <= 0. || Now <= Previous || Now - Previous > MaxStep) return false;
    const double Since = FMath::Fmod(FMath::Fmod(Now - Event, Cycle) + Cycle, Cycle);
    return Since < Now - Previous;
}

/** The train's continuous sound layers (BelmonteTrainSound.cpp), from its motion and its timetable alone: Speed (m/s,
 *  unsigned) and Accel (m/s^2 along the motion, + speeding up), as the listener hears them (service speeds times the
 *  clock's scale), and where it is in its stands (FTrainStandClock). RollSpeed: the speed the roll master was recorded
 *  at (pitch 1 there). Every machine computes the same mix from the shared clock. */
struct FTrainSoundMix
{
    /** The locomotive standing (loop), its departure (the start one-shot), its exhaust beats (the effort loop), every
     *  vehicle rolling (loop), and each rail-joint clack's volume. */
    float Idle = 0.f, Start = 0.f, Effort = 0.f, Roll = 0.f, Clack = 0.f;
    /** The roll's pitch, the effort loop's playback rate (ChuffRate) and the clacks' pitch. */
    float RollPitch = 1.f, ChuffRate = 1.f, ClackPitch = 1.f;
};

/** Where a train is in its stands, in real seconds: since it stopped at the stand it is in (negative while it is not
 *  standing), since its last departure and until its next stop (both while moving). */
struct FTrainStandClock
{
    double SinceStop = -1., SinceDepart = 1e9, UntilStop = 1e9;
};

/** A train's stand clock at service time Time: Stands (FBelmonteTrainStand: Arrive and Depart, service times repeating
 *  every Cycle), Scale service s per real s. */
template <typename TStand>
FTrainStandClock StandClock(const TArray<TStand>& Stands, double Time, double Cycle, double Scale)
{
    FTrainStandClock Clock;
    if (Cycle <= 0.) return Clock;
    const double S = FMath::Max(Scale, 1e-3);
    auto Since = [&](double Event) { return FMath::Fmod(FMath::Fmod(Time - Event, Cycle) + Cycle, Cycle); };
    for (const TStand& Stand : Stands)
    {
        const double FromArrive = Since(Stand.Arrive);
        if (FromArrive < FMath::Fmod(Stand.Depart - Stand.Arrive + Cycle, Cycle)) Clock.SinceStop = FromArrive / S;
        Clock.SinceDepart = FMath::Min(Clock.SinceDepart, Since(Stand.Depart) / S);
        Clock.UntilStop = FMath::Min(Clock.UntilStop, (FromArrive > 0. ? Cycle - FromArrive : 0.) / S);
    }
    return Clock;
}

/** A steam engine's exhaust beats per second: BeatsPerRev a revolution of its WheelM driving wheels (4 v / (pi 1.9)). */
inline double ChuffBeats(double Speed, double WheelM = 1.9, double BeatsPerRev = 4.)
{
    return BeatsPerRev * FMath::Max(Speed, 0.) / (UE_DOUBLE_PI * WheelM);
}

/** The effort loop's playback rate: its recorded LoopBeats per second (make.py CHUFF_BEATS_PER_S) brought to the
 *  engine's beats, within MinRate..MaxRate (towards MaxRate the beats merge, SoundMix fades them under the roll). */
inline float ChuffRate(double Speed, double LoopBeats, double MinRate = .5, double MaxRate = 2.)
{
    return float(FMath::Clamp(ChuffBeats(Speed) / FMath::Max(LoopBeats, 1e-3), MinRate, MaxRate));
}

/** The sound of a train at Speed (m/s, as heard) and Accel (m/s2), Stand its stand clock. A steam engine is loud
 *  stopping, not stopped: its steam (the idle loop) swells in over the last Swell s of the braking, full at the stop
 *  (where the blow-off blast plays, StopCues), drops to a faint simmer (Simmer, about -25 dB under the cruise) within
 *  1.5 s and is gone SimmerOut s after the stop. From the departure the start, the engine's build-up (StartSeconds
 *  long, played from the departure), fades in over StartIn s and hands over in its last second to the effort loop, its
 *  beats at the driving wheels' rate. Both are loud through the soft start (SoftStart s) and while the train
 *  accelerates, silent braking, and fade under the roll as it reaches its cruise or the beats merge (MaxRate). */
inline FTrainSoundMix SoundMix(double Speed, double Accel, double RollSpeed, const FTrainStandClock& Stand,
    double StartSeconds, double LoopBeats, double MaxRate = 2., double Swell = 9., double Simmer = .18,
    double SimmerOut = 10., double StartIn = .5, double SoftStart = 12.)
{
    auto Step = [](double A, double B, double X) { return float(FMath::SmoothStep(A, B, X)); };
    const double Fast = FMath::Clamp(Speed / FMath::Max(RollSpeed, 1.), 0., 1.6);
    FTrainSoundMix M;
    if (Stand.SinceStop >= 0.)
    {
        const double T = Stand.SinceStop;
        const float Faint = float(Simmer) * (1.f - Step(1.5, SimmerOut, T));
        M.Idle = FMath::Lerp(Faint, 1.f, 1.f - Step(0., 1.5, T));
    }
    else
    {
        const double T = Stand.SinceDepart;
        M.Idle = Accel < -.04 ? 1.f - Step(0., Swell, Stand.UntilStop) : 0.f;
        const float Follow = Accel < -.04 ? 0.f : FMath::Max(Step(.04, .3, Accel), 1.f - Step(SoftStart, SoftStart + 4., T));
        const float Hand = Step(StartSeconds - 1., StartSeconds, T);
        M.Start = Step(0., StartIn, T) * (1.f - Hand) * Follow;
        M.Effort = Hand * Follow * (1.f - Step(.8 * MaxRate, MaxRate, ChuffBeats(Speed) / FMath::Max(LoopBeats, 1e-3)));
    }
    M.ChuffRate = ChuffRate(Speed, LoopBeats, .5, MaxRate);
    // The roll grows with the speed, held down under 30 km/h where the joint clacks carry the rhythm, and its pitch
    // rises gently with it (0.8 standing, 1 at RollSpeed, at most 1.15).
    M.Roll = Step(.2, 4., Speed) * float(.35 + .65 * FMath::Min(Fast, 1.)) * (.55f + .45f * Step(3., 8.3, Speed))
        * (1.f - .35f * FMath::Max(M.Start, M.Effort));
    M.RollPitch = float(FMath::Min(.8 + .2 * FMath::Max(Speed, 0.) / FMath::Max(RollSpeed, 1.), 1.15));
    M.Clack = Step(.8, 5., Speed) * float(.5 + .5 * FMath::Min(Fast, 1.));
    M.ClackPitch = float(.92 + .16 * FMath::Min(Fast, 1.));
    return M;
}

/** Rail joints (every RailLength m) a bogie passed going from chainage Previous to Now (m), either way: one clack each.
 *  At most 4 a frame (a clock jump replays nothing more). */
inline int32 JointsCrossed(double Previous, double Now, double RailLength)
{
    if (RailLength <= 0.) return 0;
    const int64 A = int64(FMath::FloorToDouble(Previous / RailLength)), B = int64(FMath::FloorToDouble(Now / RailLength));
    return int32(FMath::Min<int64>(FMath::Abs(B - A), 4));
}

/** The brake cue into a stand: it ends at the stop (Arrive, service s) and starts with the timetable's deceleration
 *  (BrakeStart) when its length fits that phase at a pitch within MinPitch..MaxPitch; otherwise it keeps that pitch
 *  limit and only its end stays on the stop. CueSeconds: the cue's real length; Scale: service s per real s. Returns
 *  the service time it starts; Pitch is what it plays at. */
inline double BrakeCue(double BrakeStart, double Arrive, double CueSeconds, double Scale, float& Pitch,
    double MinPitch = .75, double MaxPitch = 1.33)
{
    const double S = FMath::Max(Scale, 1e-3);
    const double Phase = FMath::Max(Arrive - BrakeStart, 1e-3) / S;      // real seconds
    Pitch = float(FMath::Clamp(CueSeconds / Phase, MinPitch, MaxPitch));
    return Arrive - CueSeconds / Pitch * S;
}

/** The cues of a stop, service times: the brake cue (BrakeCue: its start and Pitch) and the blow-off, one strong steam
 *  blast at the stop itself. */
struct FTrainStopCues
{
    double Brake = 0., Blast = 0.;
    float Pitch = 1.f;
};
inline FTrainStopCues StopCues(double BrakeStart, double Arrive, double BrakeSeconds, double Scale)
{
    FTrainStopCues Cues;
    Cues.Brake = BrakeCue(BrakeStart, Arrive, BrakeSeconds, Scale, Cues.Pitch);
    Cues.Blast = Arrive;
    return Cues;
}
}
