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
#endif
