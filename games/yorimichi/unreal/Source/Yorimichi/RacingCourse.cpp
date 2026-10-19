#include "RacingCourse.h"
#include "Algo/BinarySearch.h"
#include "Dom/JsonObject.h"

bool FRacingPolylineCourse::Set(const TArray<FVector>& InPoints, double InFinishS, const FVector& InOriginCm)
{
    Points = InPoints;
    OriginCm = InOriginCm;
    Cumulative.Reset();
    Lap = 0.;
    if (Points.Num() < 3) return false;
    double Area = 0.;
    Cumulative.Add(0.);
    for (int32 I = 0; I < Points.Num(); ++I)
    {
        const FVector& A = Points[I];
        const FVector& B = Points[(I + 1) % Points.Num()];
        Lap += FVector2D::Distance(FVector2D(A), FVector2D(B));
        Cumulative.Add(Lap);
        Area += A.X * B.Y - B.X * A.Y;
    }
    Turn = Area >= 0. ? 1. : -1.;
    FinishS = InFinishS;
    return IsValid();
}

bool FRacingPolylineCourse::Parse(const TSharedPtr<FJsonObject>& Track, const FVector& InOriginCm, FString& Error)
{
    const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
    double Finish = 0.;
    if (!Track || !Track->TryGetArrayField(TEXT("points"), List) || !Track->TryGetNumberField(TEXT("finish_s"), Finish))
    {
        Error = TEXT("a track needs points and finish_s");
        return false;
    }
    TArray<FVector> Read;
    for (const TSharedPtr<FJsonValue>& Value : *List)
    {
        const TArray<TSharedPtr<FJsonValue>>* P = nullptr;
        if (!Value->TryGetArray(P) || P->Num() < 2) { Error = TEXT("a point needs x and y"); return false; }
        Read.Emplace((*P)[0]->AsNumber(), (*P)[1]->AsNumber(), P->Num() > 2 ? (*P)[2]->AsNumber() : 0.);
    }
    if (!Set(Read, Finish, InOriginCm)) { Error = TEXT("fewer than three points or no length"); return false; }
    return true;
}

FVector FRacingPolylineCourse::PlanAt(double FromFirst, FVector2D* Direction) const
{
    if (!IsValid()) return FVector::ZeroVector;
    double D = FMath::Fmod(FromFirst, Lap);
    if (D < 0.) D += Lap;
    // The segment whose start is the last cumulative length at or below D.
    int32 I = FMath::Clamp(int32(Algo::UpperBound(Cumulative, D)) - 1, 0, Points.Num() - 1);
    const FVector& A = Points[I];
    const FVector& B = Points[(I + 1) % Points.Num()];
    const double Length = FMath::Max(Cumulative[I + 1] - Cumulative[I], 1e-6);
    const double T = FMath::Clamp((D - Cumulative[I]) / Length, 0., 1.);
    if (Direction) *Direction = FVector2D(B - A).GetSafeNormal();
    return FMath::Lerp(A, B, T);
}

FVector FRacingPolylineCourse::At(double S, double Offset, float* Yaw) const
{
    FVector2D Dir(1., 0.);
    FVector P = PlanAt(FinishS + S, &Dir);
    // Smooth the heading over a few metres either side, so a runner turns gradually round a sampled bend.
    FVector2D Behind = Dir, Ahead = Dir;
    PlanAt(FinishS + S - 2., &Behind);
    PlanAt(FinishS + S + 2., &Ahead);
    const FVector2D Smooth = (Behind + Dir * 2. + Ahead).GetSafeNormal();
    if (!Smooth.IsNearlyZero()) Dir = Smooth;
    // Outwards is right of the running direction on a counter-clockwise course, left on a clockwise one.
    const FVector2D Out = FVector2D(Dir.Y, -Dir.X) * Turn;
    P.X += Out.X * Offset;
    P.Y += Out.Y * Offset;
    if (Yaw) *Yaw = float(-FMath::RadiansToDegrees(FMath::Atan2(Dir.Y, Dir.X)));
    return World(P);
}

FVector FRacingPolylineCourse::Centre() const
{
    FBox Box(ForceInit);
    for (const FVector& P : Points) Box += P;
    return World(Box.GetCenter());
}

double FRacingCourse::LaneOffset(int32 Index, int32 Count) const
{
    if (Count <= 1) return (InnerLane + OuterLane) * .5;
    return FMath::Lerp(InnerLane, OuterLane, double(FMath::Clamp(Index, 0, Count - 1)) / double(Count - 1));
}

FVector FRacingCourse::Centre() const
{
    return bOval ? Oval.World(Oval.Origin.X, Oval.Origin.Y) : Line.Centre();
}

bool RacingGround::Pick(TConstArrayView<FHit> Hits, double AuthoredZ, double& OutZ)
{
    OutZ = AuthoredZ;
    bool bFound = false;
    for (const FHit& Hit : Hits)
    {
        if (!FMath::IsFinite(Hit.Z) || Hit.Normal.GetSafeNormal().Z < MinUp) continue;
        if (Hit.Z > AuthoredZ + Above || Hit.Z < AuthoredZ - Below) continue;
        if (!bFound || FMath::Abs(Hit.Z - AuthoredZ) < FMath::Abs(OutZ - AuthoredZ)) OutZ = Hit.Z;
        bFound = true;
    }
    return bFound;
}
