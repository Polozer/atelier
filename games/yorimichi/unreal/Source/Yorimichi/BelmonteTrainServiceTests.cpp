#include "BelmonteTrainService.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FBelmonteTrainLineTest, "Yorimichi.Belmonte.TrainLine",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// A 1 km straight line east with a 200 m loop 4 m to the north (Unreal -y), and two trains: A runs up 0 -> 1000 m in
// 100 s, B down 1000 -> 0 m over the same 100 s on the loop track; the cycle is 200 s.
static const TCHAR* LineJson = TEXT(R"({
 "line": {"main": [[0,0,0,0],[500,50000,0,1000],[1000,100000,0,0]],
          "loop": {"start": 400, "end": 600, "points": [[400,40000,0,800],[410,41000,-400,820],[590,59000,-400,820],[600,60000,0,800]]},
          "viewpoints": [{"s": 250}]},
 "service": {"cycle_s": 200, "clock_start_s": 0, "trains": [
   {"name": "A", "t0": 0, "dt": 50, "s": [0,500,1000,1000], "loop_track": []},
   {"name": "B", "t0": 0, "dt": 50, "s": [1000,500,0,0], "loop_track": [[0,100]]}]}
})");

bool FBelmonteTrainLineTest::RunTest(const FString&)
{
    TSharedPtr<FJsonObject> Root;
    TestTrue(TEXT("Fixture parses"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(LineJson), Root));
    FBelmonteTrainLine Line; FString Error;
    TestTrue(TEXT("Line parses: ") + Error, Line.Parse(Root, Error));
    TestEqual(TEXT("Two trains"), Line.Trains.Num(), 2);
    TestTrue(TEXT("Chainage interpolates"), FMath::IsNearlyEqual(Line.Chainage(0, 25.), 250., 1e-6));
    TestTrue(TEXT("The cycle repeats"), FMath::IsNearlyEqual(Line.Chainage(0, 225.), 250., 1e-6));
    TestTrue(TEXT("Times before t0 wrap"), FMath::IsNearlyEqual(Line.Chainage(0, -175.), 250., 1e-6));
    TestTrue(TEXT("Up speed is positive, 10 m/s"), FMath::IsNearlyEqual(Line.Speed(0, 30.), 10., 1e-6));
    TestTrue(TEXT("Down speed is negative"), Line.Speed(1, 30.) < 0.);
    TestTrue(TEXT("Main line height interpolates"), FMath::IsNearlyEqual(Line.Point(250., false).Z, 500., 1e-6));
    TestTrue(TEXT("B is on the loop track"), Line.OnLoopTrack(1, 50.) && !Line.OnLoopTrack(0, 50.));
    TestTrue(TEXT("The loop track is offset from the main line"), FMath::IsNearlyEqual(Line.Point(500., true).Y, -400., 1e-6));
    TestTrue(TEXT("Outside the loop both tracks agree"), Line.Point(300., true).Equals(Line.Point(300., false)));
    double Where = 0.;
    const double Crossing = Line.NextCrossing(1., &Where);
    TestTrue(TEXT("The trains cross at mid-line, in the loop"), FMath::IsNearlyEqual(Crossing, 50., .51) && Where >= 400. && Where <= 600.);
    int32 Which = -1;
    TestTrue(TEXT("Next passing of 250 m"), FMath::IsNearlyEqual(Line.NextPassing(1., 250., &Which), 25., .51) && Which == 0);

    // A 24 m vehicle with bogies at +-8.5 m on the straight: its origin is its centre, on the rail, heading east (+x).
    const FTransform Flat = Line.Place(100., -8.5, 8.5, false);
    TestTrue(TEXT("Vehicle origin at its chainage"), Flat.GetLocation().Equals(FVector(10000., 0., 200.), .01));
    TestTrue(TEXT("Vehicle heads up the line"), FMath::IsNearlyEqual(Flat.Rotator().Yaw, 0., 1e-3));
    TestTrue(TEXT("Vehicle pitches up the grade"), Flat.Rotator().Pitch > 1.);
    // Asymmetric bogies (the brake van): the origin still sits at the vehicle's own chainage.
    const FTransform Van = Line.Place(100., -3.3, 3.55, false);
    TestTrue(TEXT("Asymmetric bogies keep the origin"), FMath::IsNearlyEqual(Van.GetLocation().X, 10000., .5));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FBelmonteTrainBoardsTest, "Yorimichi.Belmonte.TrainBoards",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// Two trains shuttling 0 <-> 1000 m on a 400 s cycle, sampled every 10 s: each stands 100 s at each terminus. A stands at
// 1000 m from 190 to 290 s and at 0 m from 390 to 90 s (across the cycle's end); B runs the same 200 s later.
static FBelmonteTrainLine ShuttleLine()
{
    FBelmonteTrainLine Line;
    Line.Cycle = 400.;
    for (int32 Train = 0; Train < 2; ++Train)
    {
        FBelmonteTrainRun& Run = Line.Trains.AddDefaulted_GetRef();
        Run.Name = Train ? TEXT("B") : TEXT("A");
        Run.T0 = Train * 200.;
        Run.Dt = 10.;
        for (int32 K = 0; K < 40; ++K)
            Run.S.Add(K < 10 ? 0.f : K < 19 ? float((K - 9) * 100) : K < 30 ? 1000.f : float(1000 - (K - 29) * 100));
    }
    return Line;
}

bool FBelmonteTrainBoardsTest::RunTest(const FString&)
{
    const FBelmonteTrainLine Line = ShuttleLine();
    const TArray<FBelmonteTrainStop> Far = Line.Stops(1000.), Near = Line.Stops(0.);
    TestEqual(TEXT("Each train stands once a cycle at each end"), Far.Num(), 2);
    TestEqual(TEXT("... at both ends"), Near.Num(), 2);
    if (Far.Num() != 2 || Near.Num() != 2) return false;
    TestTrue(TEXT("A arrives at 1000 m at 190 s and leaves at 290 s"), Far[0].Train == 0 && FMath::IsNearlyEqual(Far[0].Arrive, 190.) && FMath::IsNearlyEqual(Far[0].Depart, 290.));
    TestTrue(TEXT("B arrives at 1000 m at 390 s and leaves across the cycle's end"), Far[1].Train == 1 && FMath::IsNearlyEqual(Far[1].Arrive, 390.) && FMath::IsNearlyEqual(Far[1].Depart, 90.));
    TestTrue(TEXT("A's stand at 0 m spans the cycle's end"), Near[1].Train == 0 && FMath::IsNearlyEqual(Near[1].Arrive, 390.) && FMath::IsNearlyEqual(Near[1].Depart, 90.));
    TestTrue(TEXT("B arrives at 0 m at 190 s"), Near[0].Train == 1 && FMath::IsNearlyEqual(Near[0].Arrive, 190.));

    auto Next = [&](const TArray<FBelmonteTrainStop>& Stops, double Time, int32 Count = 2) { return FBelmonteTrainLine::NextArrivals(Stops, Line.Cycle, Time, Count); };
    // Nobody at 1000 m at 100 s: A in 90 s, then B in 290 s.
    TArray<FBelmonteTrainArrival> A = Next(Far, 100.);
    TestTrue(TEXT("Next and after-next while the platform is empty"), A.Num() == 2 && A[0].Train == 0 && !A[0].bAtPlatform && FMath::IsNearlyEqual(A[0].In, 90.)
        && A[1].Train == 1 && FMath::IsNearlyEqual(A[1].In, 290.));
    // A standing (200 s): at the platform first, B next in 190 s.
    A = Next(Far, 200.);
    TestTrue(TEXT("A standing train comes first"), A.Num() == 2 && A[0].Train == 0 && A[0].bAtPlatform && A[0].In == 0. && A[1].Train == 1 && FMath::IsNearlyEqual(A[1].In, 190.));
    TestTrue(TEXT("At the very arrival the train is at the platform"), Next(Far, 190.)[0].bAtPlatform);
    TestTrue(TEXT("Once it has left, the other train is next"), !Next(Far, 291.)[0].bAtPlatform && Next(Far, 291.)[0].Train == 1);
    // B's stand across the cycle's end (50 s): at the platform, A next in 140 s.
    A = Next(Far, 50.);
    TestTrue(TEXT("A stand across the cycle's end"), A[0].Train == 1 && A[0].bAtPlatform && A[1].Train == 0 && FMath::IsNearlyEqual(A[1].In, 140.));
    // The cycle repeats, before and after.
    A = Next(Far, 100. + 3 * Line.Cycle);
    TestTrue(TEXT("Cycles later"), FMath::IsNearlyEqual(A[0].In, 90.) && FMath::IsNearlyEqual(A[1].In, 290.));
    A = Next(Far, 100. - 2 * Line.Cycle);
    TestTrue(TEXT("Before the clock's start"), FMath::IsNearlyEqual(A[0].In, 90.) && A[0].Train == 0);
    // More arrivals than trains: the next cycle's follow.
    A = Next(Far, 100., 3);
    TestTrue(TEXT("The third arrival is A's next one"), A.Num() == 3 && A[2].Train == 0 && FMath::IsNearlyEqual(A[2].In, 490.));
    TestTrue(TEXT("At 0 m at 100 s: B in 90 s, A in 290 s"), Next(Near, 100.)[0].Train == 1 && FMath::IsNearlyEqual(Next(Near, 100.)[1].In, 290.));
    TestEqual(TEXT("No stops, no arrivals"), FBelmonteTrainLine::NextArrivals({}, Line.Cycle, 0., 2).Num(), 0);

    // Real minutes: whole minutes left, "arrive" under one, "à quai" when standing; the dev clock speed divides.
    auto In = [](double Seconds) { FBelmonteTrainArrival R; R.Train = 0; R.In = Seconds; return R; };
    FBelmonteTrainArrival Standing; Standing.Train = 0; Standing.bAtPlatform = true;
    TestEqual(TEXT("Standing"), FBelmonteTrainLine::Countdown(Standing, 1.), FString(TEXT("à quai")));
    TestEqual(TEXT("Under a minute"), FBelmonteTrainLine::Countdown(In(59.), 1.), FString(TEXT("arrive")));
    TestEqual(TEXT("One minute"), FBelmonteTrainLine::Countdown(In(60.), 1.), FString(TEXT("dans 1 min")));
    TestEqual(TEXT("Five minutes and a bit"), FBelmonteTrainLine::Countdown(In(5 * 60. + 59.), 1.), FString(TEXT("dans 5 min")));
    TestEqual(TEXT("Clock ten times faster: 600 service s are one real minute"), FBelmonteTrainLine::Countdown(In(600.), 10.), FString(TEXT("dans 1 min")));
    TestEqual(TEXT("... and 590 are under it"), FBelmonteTrainLine::Countdown(In(590.), 10.), FString(TEXT("arrive")));
    TestEqual(TEXT("Clock at half speed: 90 service s are three real minutes"), FBelmonteTrainLine::Countdown(In(90.), .5), FString(TEXT("dans 3 min")));
    TestEqual(TEXT("No train"), FBelmonteTrainLine::Countdown(FBelmonteTrainArrival(), 1.), FString(TEXT("-")));

    // The countdown at a board follows the service clock: a minute of service time later (scale 1) it reads a minute less.
    TestEqual(TEXT("Board at 100 s"), FBelmonteTrainLine::Countdown(Next(Far, 100.)[0], 1.), FString(TEXT("dans 1 min")));
    TestEqual(TEXT("Board at 140 s"), FBelmonteTrainLine::Countdown(Next(Far, 140.)[0], 1.), FString(TEXT("arrive")));
    TestEqual(TEXT("Board at 200 s"), FBelmonteTrainLine::Countdown(Next(Far, 200.)[0], 1.), FString(TEXT("à quai")));
    TestEqual(TEXT("Board at 200 s, the train after"), FBelmonteTrainLine::Countdown(Next(Far, 200.)[1], 1.), FString(TEXT("dans 3 min")));
    return true;
}
#endif
