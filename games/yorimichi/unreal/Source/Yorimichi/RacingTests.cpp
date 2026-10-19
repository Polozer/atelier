#include "RacingService.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "RacingBetting.h"
#include "RacingBroadcast.h"
#include "RacingPlaces.h"
#include "HorseComponent.h"
#include "AtelierData.h"
#include "Dom/JsonObject.h"
#include "HRClock.h"
#include "HRContent.h"
#include "HRRules.h"
#include "HRSave.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/MemoryReader.h"
#include "Serialization/MemoryWriter.h"
#include "Net/UnrealNetwork.h"
#include <limits>

namespace RacingTest
{
    /** belmonte_courses.json: the staged copy, else the committed source beside the Unreal project. */
    FString CoursesJson()
    {
        FString Text;
        if (FFileHelper::LoadFileToString(Text, *AtelierDataPath(TEXT("racing/belmonte_courses.json")))) return Text;
        FFileHelper::LoadFileToString(Text, *FPaths::Combine(FPaths::ProjectDir(), TEXT("../world/racing/belmonte_courses.json")));
        return Text;
    }

    /** Belmonte's region origin (world/regions/belmonte/layout.py ORIGIN, in Unreal cm). */
    const FVector BelmonteOrigin(550. * 100., -4500. * 100., 210. * 100.);

    /** A world one second before its first race of the day, the race run, and the snapshot a second after its start. */
    struct FRaceFixture
    {
        FHRWorldState World;
        double Start = 0.;
        FRacingNetState Snapshot;
        bool Make(FAutomationTestBase& Test)
        {
            World = HRRules::CreateWorld(TEXT("yorimichi-racing-test"));
            HRRules::StartClock(World, 1700000000);
            const FHRRace* First = nullptr;
            for (const FHRRace& R : World.Meeting.Races)
                if (R.Status == TEXT("declared") && R.Entries.Num() >= 2) { First = &R; break; }
            if (!Test.TestNotNull(TEXT("The day has a race"), First)) return false;
            Start = HRRules::RaceStartSeconds(World, First->Key);
            HRRules::AdvanceTo(World, Start + 1.);
            ARacingService::BuildSnapshot(World, Start + 1., FRacingNetResult(), Snapshot);
            return Test.TestTrue(TEXT("The race in focus has been run"), Snapshot.Race.bRun && Snapshot.Race.Runners.Num() >= 2);
        }
    };
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingHudGroundsTest, "Yorimichi.Racing.HudGrounds",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingHudGroundsTest::RunTest(const FString&)
{
    FRacingCourse Oval;
    Oval.Oval.Lap = 4. * Oval.Oval.Half + 2. * PI * Oval.Oval.Radius;
    Oval.Oval.Z = 40.;
    auto At = [&](double X, double Y, double Z = 0.) { return Oval.Oval.World(X, Y, Z); };
    TestFalse(TEXT("Loaded course without platform bounds hides the banner"), Oval.ContainsGrounds(At(600., 525.)));
    Oval.Oval.Grounds += At(476., 443.);
    Oval.Oval.Grounds += At(747., 589.);
    TestTrue(TEXT("Hidamari infield"), Oval.ContainsGrounds(At(600., 525.)));
    TestTrue(TEXT("Grandstand arrival"), Oval.ContainsGrounds(At(563.5, 458.5, 1.)));
    TestTrue(TEXT("Grandstand upper seats"), Oval.ContainsGrounds(At(600., 453., 15.)));
    TestFalse(TEXT("City street, inside old rendering radius"), Oval.ContainsGrounds(At(560., 343.)));
    TestFalse(TEXT("Approach lane"), Oval.ContainsGrounds(At(560., 442.)));
    TestFalse(TEXT("Beyond west platform edge"), Oval.ContainsGrounds(At(475., 525.)));
    TestFalse(TEXT("Beyond east platform edge"), Oval.ContainsGrounds(At(748., 525.)));
    TestFalse(TEXT("Beyond north platform edge"), Oval.ContainsGrounds(At(600., 590.)));
    TestFalse(TEXT("Flying over the venue"), Oval.ContainsGrounds(At(600., 525., 30.)));
    TestFalse(TEXT("Under the platform"), Oval.ContainsGrounds(At(600., 525., -10.)));
    Oval.Oval.Grounds = FBox(At(500., 500.), At(700., 600.));
    TestFalse(TEXT("Invalid bounds hide the banner"), Oval.ContainsGrounds(At(600., 525.)));

    ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
    FString Error;
    if (!TestTrue(TEXT("Belmonte loaded"), Service->LoadBelmonteCourses(RacingTest::CoursesJson(), RacingTest::BelmonteOrigin, Error))) return false;
    const FRacingCourse* Turf = Service->GetCourse(ERacingVenue::Belmonte);
    if (!TestNotNull(TEXT("Belmonte turf"), Turf)) return false;
    TestTrue(TEXT("Belmonte infield"), Turf->ContainsGrounds(Turf->Centre()));
    TestTrue(TEXT("Belmonte post spectator point"), Turf->ContainsGrounds(Turf->At(15., 9.)));
    TestFalse(TEXT("Belmonte countryside"), Turf->ContainsGrounds(Turf->At(15., 100.)));
    TestFalse(TEXT("Flying over Belmonte"), Turf->ContainsGrounds(Turf->Centre() + FVector(0., 0., 3000.)));
    FRacingCourse Empty;
    TestFalse(TEXT("Unloaded venue"), Empty.ContainsGrounds(FVector::ZeroVector));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingEnglishNameTest, "Yorimichi.Racing.EnglishName",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingEnglishNameTest::RunTest(const FString&)
{
    FHRRace Race;
    Race.EventId = TEXT("test-event");
    Race.Group = 1;
    const TCHAR* Rounds[] = {TEXT("final"), TEXT("semi"), TEXT("qualif"), TEXT("barrage"), TEXT("ordinary")};
    const TCHAR* Expected[] = {TEXT("final"), TEXT("semi-final 2"), TEXT("qualifying sprint 2"), TEXT("play-off 2"), TEXT("race 2")};
    for (int32 I = 0; I < UE_ARRAY_COUNT(Rounds); ++I)
    {
        Race.Round = Rounds[I];
        TestEqual(Rounds[I], ARacingService::RaceName(Race), FString(TEXT("test-event · ")) + Expected[I]);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingBelmonteCourseTest, "Yorimichi.Racing.BelmonteCourse",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingBelmonteCourseTest::RunTest(const FString&)
{
    const FString Json = RacingTest::CoursesJson();
    if (!TestFalse(TEXT("belmonte_courses.json is readable"), Json.IsEmpty())) return false;
    ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
    FString Error;
    const bool bLoaded = Service->LoadBelmonteCourses(Json, RacingTest::BelmonteOrigin, Error);
    if (!TestTrue(TEXT("The courses parse: ") + Error, bLoaded)) return false;
    const FRacingCourse* Turf = Service->GetCourse(ERacingVenue::Belmonte, 0);
    const FRacingCourse* Sand = Service->GetCourse(ERacingVenue::Belmonte, 1);
    if (!TestNotNull(TEXT("Turf"), Turf) || !TestNotNull(TEXT("Sand"), Sand)) return false;
    TestTrue(TEXT("Turf lap 1799.84 m"), FMath::IsNearlyEqual(Turf->Lap(), 1799.841, .01));
    TestTrue(TEXT("Sand lap 1703.71 m"), FMath::IsNearlyEqual(Sand->Lap(), 1703.707, .01));
    TestTrue(TEXT("Counter-clockwise"), Turf->Line.Turn > 0.);
    // The finish (S 0) is the lane-1 point 240 m from the first sample, (-155, 607.3) in the region's plan; the post
    // stands 3.6 m further out at (-155, 610.9).
    float Yaw = 0.f;
    const FVector Finish = Turf->At(0., 0., &Yaw);
    const FVector Expected = RacingTest::BelmonteOrigin + FVector(-155. * 100., -607.3 * 100., 30.08 * 100.);
    TestTrue(FString::Printf(TEXT("Finish point %s"), *Finish.ToString()), Finish.Equals(Expected, 1.));
    TestTrue(TEXT("The post is 3.6 m outwards"), Turf->At(0., 3.6).Equals(RacingTest::BelmonteOrigin + FVector(-155. * 100., -610.9 * 100., 30.08 * 100.), 2.));
    TestTrue(FString::Printf(TEXT("Running west past the post (yaw %.1f)"), Yaw), FMath::Abs(FMath::Abs(Yaw) - 180.f) < 1.f);
    TestTrue(TEXT("A lap closes"), Turf->At(Turf->Lap(), -4.).Equals(Turf->At(0., -4.), .5));
    // Continuous: samples every half metre along every lane stay about half a metre apart (more outside a bend, less inside).
    for (const FRacingCourse* Course : {Turf, Sand})
        for (const double Lane : {Course->InnerLane, 0.})
        {
            FVector Previous = Course->At(0., Lane);
            double Longest = 0., Shortest = 1e9;
            for (double S = .5; S <= Course->Lap() + .01; S += .5)
            {
                const FVector P = Course->At(S, Lane);
                const double Step = FVector::Dist2D(P, Previous) / 100.;
                Longest = FMath::Max(Longest, Step);
                Shortest = FMath::Min(Shortest, Step);
                Previous = P;
            }
            TestTrue(FString::Printf(TEXT("No jump along lane %.1f (longest step %.3f m)"), Lane, Longest), Longest < .6);
            TestTrue(FString::Printf(TEXT("No stall along lane %.1f (shortest step %.3f m)"), Lane, Shortest), Shortest > .25);
        }
    // Lanes run inside the outer rail (2.5 m out) and the inner one (12.8 m in).
    TestTrue(TEXT("Lanes between the rails"), Turf->InnerLane > -12.8 && Turf->OuterLane < 2.5);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingHippodromeCourseTest, "Yorimichi.Racing.HippodromeCourse",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingHippodromeCourseTest::RunTest(const FString&)
{
    FRacingCourse Course;
    Course.Oval.Lap = 4. * Course.Oval.Half + 2. * PI * Course.Oval.Radius;
    Course.InnerLane = -5.;
    Course.OuterLane = 5.;
    TestTrue(TEXT("Lap 554.2 m"), FMath::IsNearlyEqual(Course.Lap(), 554.159, .01));
    float Yaw = 0.f;
    TestTrue(TEXT("The post is at finish_x on the home straight"), Course.At(0., 0., &Yaw).Equals(FVector(600. * 100., -475. * 100., 0.), .01));
    TestTrue(TEXT("Running east past the post"), FMath::Abs(Yaw) < .01f);
    FVector Previous = Course.At(0., 3.);
    double Longest = 0.;
    for (double S = .5; S <= Course.Lap() + .01; S += .5)
    {
        const FVector P = Course.At(S, 3.);
        Longest = FMath::Max(Longest, FVector::Dist2D(P, Previous) / 100.);
        Previous = P;
    }
    TestTrue(FString::Printf(TEXT("Continuous (longest step %.3f m)"), Longest), Longest < .55);
    TestTrue(TEXT("Lanes spread across the field"), FMath::IsNearlyEqual(Course.LaneOffset(0, 6), -5.) && FMath::IsNearlyEqual(Course.LaneOffset(5, 6), 5.));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingMotionTest, "Yorimichi.Racing.Motion",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingMotionTest::RunTest(const FString&)
{
    RacingTest::FRaceFixture Fixture;
    if (!Fixture.Make(*this)) return false;
    // Twice from the world, and once from the snapshot as a client receives it (serialised and read back).
    FRacingNetState Again;
    ARacingService::BuildSnapshot(Fixture.World, Fixture.Start + 1., FRacingNetResult(), Again);
    TestTrue(TEXT("The snapshot is deterministic"), Again.SameContent(Fixture.Snapshot));
    TArray<uint8> Bytes;
    FMemoryWriter Writer(Bytes);
    FRacingNetState::StaticStruct()->SerializeBin(Writer, &Fixture.Snapshot);
    FRacingNetState Received;
    FMemoryReader Reader(Bytes);
    FRacingNetState::StaticStruct()->SerializeBin(Reader, &Received);
    TestTrue(TEXT("The snapshot survives the wire"), Received.SameContent(Fixture.Snapshot));
    const FRacingNetRace& Race = Fixture.Snapshot.Race;
    for (int32 I = 0; I < Race.Runners.Num(); ++I)
    {
        const RacingMotion::FPlan Host = Race.Runners[I].Plan(Race.Distance), Client = Received.Race.Runners[I].Plan(Race.Distance);
        TestTrue(TEXT("Four splits"), Host.IsRun());
        double Previous = -1e9;
        bool bSame = true, bMonotone = true;
        for (double T = -RacingMotion::ParadeSeconds; T <= HRClock::RaceSeconds; T += .25)
        {
            double V1 = 0., V2 = 0.;
            const double D = RacingMotion::Distance(Host, T, &V1);
            bSame &= D == RacingMotion::Distance(Client, T, &V2) && V1 == V2;
            bMonotone &= D >= Previous - 1e-9;
            Previous = D;
        }
        TestTrue(TEXT("Host and client place the runner alike"), bSame);
        TestTrue(TEXT("A runner never runs backwards"), bMonotone);
        TestTrue(TEXT("Standing at the start"), FMath::IsNearlyZero(RacingMotion::Distance(Host, 0.)));
        // The parade: walking to the start, then lined up and still for the whole TV build-up.
        double Walking = 0., Still = 1.;
        TestTrue(TEXT("Walking to the start"), RacingMotion::Distance(Host, -150., &Walking) < 0. && Walking > 1.);
        for (double T = -RacingTv::WindowSeconds; T < 0.; T += 1.)
            if (!FMath::IsNearlyZero(RacingMotion::Distance(Host, T, &Still)) || Still != 0.) { AddError(FString::Printf(TEXT("Not lined up at t=%.0f"), T)); break; }
        TestTrue(TEXT("At the post on its finishing time"), FMath::IsNearlyEqual(RacingMotion::Distance(Host, Host.FinishTime()), double(Race.Distance), .01));
        for (int32 K = 0; K < 3; ++K)
            TestTrue(TEXT("Through each stage on its split"),
                FMath::IsNearlyEqual(RacingMotion::Distance(Host, Host.Splits[K]), Race.Distance * RacingMotion::StageEnd[K], .01));
        double Speed = 0.;
        RacingMotion::Distance(Host, Host.FinishTime() * .6, &Speed);
        TestTrue(FString::Printf(TEXT("A racing speed mid-race (%.1f m/s)"), Speed), Speed > 8. && Speed < 25.);
    }
    // The finishing order is the official one: lower place, earlier finishing time.
    for (const FRacingNetRunner& A : Race.Runners)
        for (const FRacingNetRunner& B : Race.Runners)
            if (A.Place < B.Place) TestTrue(TEXT("Places follow finishing times"), A.SplitMs[3] <= B.SplitMs[3]);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingSnapshotTest, "Yorimichi.Racing.Snapshot",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingSnapshotTest::RunTest(const FString&)
{
    RacingTest::FRaceFixture Fixture;
    if (!Fixture.Make(*this)) return false;
    TArray<uint8> Bytes;
    FMemoryWriter Writer(Bytes);
    FRacingNetState::StaticStruct()->SerializeBin(Writer, &Fixture.Snapshot);
    const int32 Payload = Fixture.Snapshot.PayloadBytes();
    AddInfo(FString::Printf(TEXT("Snapshot payload %d bytes (%d as a binary archive), %d runners, %d standings"), Payload, Bytes.Num(),
        Fixture.Snapshot.Race.Runners.Num(), Fixture.Snapshot.Standings.Num()));
    TestTrue(FString::Printf(TEXT("The snapshot stays small (%d bytes)"), Payload), Payload > 0 && Payload < 2048);
    TestTrue(TEXT("At most the rules' field"), Fixture.Snapshot.Race.Runners.Num() <= HRRules::MaxRunners);
    TestTrue(TEXT("Standings"), Fixture.Snapshot.Standings.Num() > 0 && Fixture.Snapshot.Standings.Num() <= 6);
    // The venue rule: Grand Prix days at Belmonte, the ordinary days of a season alternating from Hidamari.
    int32 Hidamari = 0, Belmonte = 0;
    for (int32 T = 0; T < HRClock::DaysPerSeason; ++T)
    {
        const ERacingVenue V = ARacingService::VenueForDay(T);
        if (HRClock::IsGrandPrixDay(T)) TestTrue(TEXT("Grand Prix at Belmonte"), V == ERacingVenue::Belmonte);
        else (V == ERacingVenue::Hidamari ? Hidamari : Belmonte)++;
    }
    TestEqual(TEXT("Ordinary days shared evenly"), Hidamari, 4);
    // After the race is shown: the next race comes into focus and the podium stays as the last result.
    FRacingNetState Later;
    ARacingService::BuildSnapshot(Fixture.World, Fixture.Start + HRClock::RaceSeconds + 1., FRacingNetResult(), Later);
    TestEqual(TEXT("The last result is the race just run"), Later.Last.Key, Fixture.Snapshot.Race.Key);
    TestEqual(TEXT("A podium of three"), Later.Last.Top.Num(), FMath::Min(3, Fixture.Snapshot.Race.Runners.Num()));
    TestNotEqual(TEXT("The next race in focus"), Later.Race.Key, Fixture.Snapshot.Race.Key);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingSaveTest, "Yorimichi.Racing.Save",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingSaveTest::RunTest(const FString&)
{
    const FString Path = FPaths::ConvertRelativePathToFull(FPaths::AutomationTransientDir() / FString::Printf(TEXT("racing-%s/world.json"),
        *FGuid::NewGuid().ToString(EGuidFormats::Digits)));
    ARacingService* First = NewObject<ARacingService>(GetTransientPackage());
    TestTrue(TEXT("A new world is created"), First->OpenWorld(Path, TEXT("save-test")));
    TestTrue(TEXT("and saved"), FPaths::FileExists(Path));
    TestTrue(TEXT("Its clock is anchored"), First->GetWorldState().EpochUnix != 0);
    TestTrue(TEXT("A later save"), First->SaveNow());
    // Another session on the same machine: the saved world, not a new one from its own seed.
    ARacingService* Second = NewObject<ARacingService>(GetTransientPackage());
    TestTrue(TEXT("The world is loaded"), Second->OpenWorld(Path, TEXT("another-seed")));
    TestEqual(TEXT("Same seed"), Second->GetWorldState().Seed, FString(TEXT("save-test")));
    TestEqual(TEXT("Same world, byte for byte"), HRSave::ToJson(Second->GetWorldState()), HRSave::ToJson(First->GetWorldState()));
    FHRWorldState Untouched;
    TestFalse(TEXT("A missing file loads nothing"), ARacingService::LoadWorldFile(Path + TEXT(".missing"), Untouched));
    FFileHelper::SaveStringToFile(TEXT("not a world"), *(Path + TEXT(".bad")));
    TestFalse(TEXT("Nor does a broken one"), ARacingService::LoadWorldFile(Path + TEXT(".bad"), Untouched));
    IFileManager::Get().DeleteDirectory(*FPaths::GetPath(Path), false, true);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingSaveSafetyTest, "Yorimichi.Racing.SaveSafety",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingSaveSafetyTest::RunTest(const FString&)
{
    const FString Dir = FPaths::ConvertRelativePathToFull(FPaths::AutomationTransientDir() / FString::Printf(TEXT("racing-safety-%s"),
        *FGuid::NewGuid().ToString(EGuidFormats::Digits)));
    // The service reports each failure as an error: expected here.
    AddExpectedError(TEXT("is not an admissible world"), EAutomationExpectedErrorFlags::Contains, 2);
    AddExpectedError(TEXT("could not save the world"), EAutomationExpectedErrorFlags::Contains, 1);
    IFileManager& Files = IFileManager::Get();
    const double Now = double((FDateTime::UtcNow() - FDateTime(1970, 1, 1)).GetTotalSeconds());

    // A save that is not an admissible world is kept aside, then a new world is created.
    {
        const FString Path = Dir / TEXT("aside/world.json");
        FFileHelper::SaveStringToFile(TEXT("{\"rulesVersion\":\"something else\"}"), *Path);
        ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
        TestTrue(TEXT("A new world opens"), Service->OpenWorld(Path, TEXT("safety")));
        TArray<FString> Aside;
        Files.FindFiles(Aside, *(FPaths::GetPath(Path) / TEXT("world.json.unreadable-*")), true, false);
        TestEqual(TEXT("The unreadable save is kept aside"), Aside.Num(), 1);
        FString Kept;
        if (Aside.Num()) FFileHelper::LoadFileToString(Kept, *(FPaths::GetPath(Path) / Aside[0]));
        TestTrue(TEXT("unchanged"), Kept.Contains(TEXT("something else")));
        TestFalse(TEXT("No temporary file is left"), FPaths::FileExists(Path + TEXT(".tmp")));
        FHRWorldState Reloaded;
        TestTrue(TEXT("The new world is saved whole"), ARacingService::LoadWorldFile(Path, Reloaded));
    }

    // When it cannot be kept aside, it stays exactly where it is and no world opens.
    {
        const FString Path = Dir / TEXT("stuck/world.json");
        const FString Original = TEXT("{\"not\":\"a world\"}");
        FFileHelper::SaveStringToFile(Original, *Path);
        // Every aside name of the next minute is taken by a directory that a rename cannot replace.
        for (int32 S = -2; S < 60; ++S)
            FFileHelper::SaveStringToFile(TEXT("x"), *(Path + FString::Printf(TEXT(".unreadable-%lld/keep"), int64(Now) + S)));
        ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
        TestFalse(TEXT("No world opens"), Service->OpenWorld(Path, TEXT("safety")));
        TestFalse(TEXT("racing stays off"), Service->HasWorld());
        TestFalse(TEXT("and says why"), Service->GetPersistenceError().IsEmpty());
        FString Kept;
        FFileHelper::LoadFileToString(Kept, *Path);
        TestEqual(TEXT("The original save is untouched"), Kept, Original);
        TestFalse(TEXT("nothing is saved"), Service->SaveNow());
        FFileHelper::LoadFileToString(Kept, *Path);
        TestEqual(TEXT("still untouched"), Kept, Original);
    }

    // A failed save keeps the accepted world in memory and dirty; the next one writes it.
    {
        const FString Path = Dir / TEXT("retry/world.json");
        ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
        TestTrue(TEXT("A world opens"), Service->OpenWorld(Path, TEXT("safety")));
        const FString Accepted = HRSave::ToJson(Service->GetWorldState());
        FString OnDisk;
        FFileHelper::LoadFileToString(OnDisk, *Path);
        // The temporary file's name is taken by a directory: the write fails.
        FFileHelper::SaveStringToFile(TEXT("x"), *(Path + TEXT(".tmp/keep")));
        TestFalse(TEXT("The save fails"), Service->SaveNow());
        TestFalse(TEXT("and says why"), Service->GetPersistenceError().IsEmpty());
        TestTrue(TEXT("The world is still open"), Service->HasWorld());
        TestEqual(TEXT("unchanged in memory"), HRSave::ToJson(Service->GetWorldState()), Accepted);
        FString After;
        FFileHelper::LoadFileToString(After, *Path);
        TestEqual(TEXT("The previous save is intact"), After, OnDisk);
        Files.DeleteDirectory(*(Path + TEXT(".tmp")), false, true);
        TestTrue(TEXT("The next save succeeds"), Service->SaveNow());
        TestTrue(TEXT("and clears the error"), Service->GetPersistenceError().IsEmpty());
        FHRWorldState Reloaded;
        TestTrue(TEXT("The saved world loads"), ARacingService::LoadWorldFile(Path, Reloaded));
        TestEqual(TEXT("as accepted"), HRSave::ToJson(Reloaded), HRSave::ToJson(Service->GetWorldState()));
    }
    Files.DeleteDirectory(*Dir, false, true);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingGroundTest, "Yorimichi.Racing.Ground",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingGroundTest::RunTest(const FString&)
{
    using RacingGround::FHit;
    double Z = 0.;
    TestFalse(TEXT("No hit: the authored height"), RacingGround::Pick({}, 3000., Z));
    TestEqual(TEXT("no hit z"), Z, 3000.);
    const FHit Wall{3100., FVector(1., 0., 0.)};
    const FHit Rail{3050., FVector(0., .8, .2)};
    TestFalse(TEXT("A wall or a rail is not ground"), RacingGround::Pick({Wall, Rail}, 3000., Z));
    TestEqual(TEXT("and leaves the authored height"), Z, 3000.);
    const FHit Roof{3200., FVector::UpVector};
    const FHit Turf{2970., FVector(.1, 0., .99)};
    TestTrue(TEXT("The turf under a roof"), RacingGround::Pick({Roof, Wall, Turf}, 3000., Z));
    TestEqual(TEXT("is the ground"), Z, 2970.);
    TestTrue(TEXT("whatever the order"), RacingGround::Pick({Turf, Roof}, 3000., Z) && Z == 2970.);
    const FHit Deep{3000. - RacingGround::Below - 1., FVector::UpVector};
    const FHit High{3000. + RacingGround::Above + 1., FVector::UpVector};
    TestFalse(TEXT("Outside the window is not ground"), RacingGround::Pick({Deep, High}, 3000., Z));
    const FHit Steep{2990., FVector(.8, 0., .6)};
    TestFalse(TEXT("A slope steeper than 45 degrees is not ground"), RacingGround::Pick({Steep}, 3000., Z));
    const FHit Bank{2990., FVector(.6, 0., .8)};
    TestTrue(TEXT("A banked turn is"), RacingGround::Pick({Bank}, 3000., Z) && Z == 2990.);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingTvPlacementTest, "Yorimichi.Racing.TvPlacement",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingTvPlacementTest::RunTest(const FString&)
{
    const FVector Origin = RacingTest::BelmonteOrigin;
    const FString AuthoredJson = TEXT("{\"tv_spots\":[")
        TEXT("{\"id\":\"osteria_front\",\"pivot_cm\":[-2600,-190,248],\"yaw\":180,\"watch_cm\":[-3040,-160,18],\"watch_yaw\":-4,\"scale\":1.4},")
        TEXT("{\"id\":\"osteria_back\",\"pivot_cm\":[-4050,485,248],\"yaw\":0,\"watch_cm\":[-3700,160,18],\"watch_yaw\":136.2,\"scale\":1.4},")
        TEXT("{\"id\":\"salon_paris\",\"pivot_cm\":[7500,-29720,3255],\"yaw\":-90,\"watch_cm\":[7500,-30150,3015],\"watch_yaw\":90,\"scale\":1.4},")
        TEXT("{\"id\":\"salon_bar\",\"pivot_cm\":[5750,-31637.6,3305],\"yaw\":90,\"watch_cm\":[5750,-31160,3015],\"watch_yaw\":-90,\"scale\":1.3}]}");
    TArray<RacingTv::FSpot> Authored;
    FString Error;
    if (!TestTrue(TEXT("Authored runtime tv_spots parse"), RacingTv::ParseSpots(AuthoredJson, Authored, &Error) && Authored.Num() == 4))
        return false;
    const int32 Front = RacingTv::FindSpot(TEXT("osteria_front"), Authored);
    if (!TestTrue(TEXT("The osteria's front screen"), Authored.IsValidIndex(Front))) return false;
    const RacingTv::FSpot& Spot = Authored[Front];
    // Haras Valley's frame is the region's: its watch point (-3040, -160) cm is the osteria's map stop, plan (-30.4, 1.6) m.
    const FVector Watch = Origin + Spot.Watch;
    TestTrue(FString::Printf(TEXT("The watch point is the osteria stop (%s)"), *Watch.ToString()),
        Watch.Equals(Origin + FVector(-30.4 * 100., -1.6 * 100., 18.), .5));
    // The picture stands 11.2 cm off the wall, facing west into the taproom, 2.3 m over the floor.
    const FTransform Mount = RacingTv::SpotTransform(Spot, Origin);
    TestTrue(TEXT("Facing west"), Mount.GetRotation().GetForwardVector().Equals(FVector(-1., 0., 0.), 1e-4));
    TestTrue(TEXT("The picture's centre"), RacingTv::ScreenCentre(Spot, Origin).Equals(Origin + FVector(-2600. - RacingTv::PictureFront * Spot.Scale, -190., 248.), .01));
    TestTrue(TEXT("1.3 to 1.5 times Haras Valley's screen"), Spot.Scale >= 1.3f && Spot.Scale <= 1.5f);
    TestTrue(TEXT("2.3 m over the floor"), FMath::IsNearlyEqual(Spot.Pivot.Z - Spot.Watch.Z, 230., .01));
    for (const RacingTv::FSpot& S : Authored)
    {
        // Every watch point is in front of its screen, within the capture's 25 m, and faces it within 50 degrees.
        const FVector Centre = RacingTv::ScreenCentre(S, Origin), At = Origin + S.Watch;
        const FVector Facing = FRotator(0.f, S.Yaw, 0.f).Vector();
        TestTrue(FString::Printf(TEXT("%s: watched from the front"), S.Id), FVector::DotProduct(At - Centre, Facing) > 0.);
        TestTrue(FString::Printf(TEXT("%s: within 25 m"), S.Id), FVector::Dist(At, Centre) < 2500.);
        const float ToScreen = float(FMath::RadiansToDegrees(FMath::Atan2(Centre.Y - At.Y, Centre.X - At.X)));
        TestTrue(FString::Printf(TEXT("%s: the viewer faces it"), S.Id), FMath::Abs(FMath::FindDeltaAngleDegrees(S.WatchYaw, ToScreen)) < 50.f);
    }
    TArray<RacingTv::FSpot> Parsed;
    const FString CustomJson = TEXT("{\"tv_spots\":[")
        TEXT("{\"id\":\"osteria_front\",\"pivot_cm\":[-2500,-100,248],\"yaw\":175,\"watch_cm\":[-2940,-70,18],\"watch_yaw\":-9,\"scale\":1.4},")
        TEXT("{\"id\":\"osteria_back\",\"pivot_cm\":[-4050,485,248],\"yaw\":0,\"watch_cm\":[-3700,160,18],\"watch_yaw\":136.2,\"scale\":1.4},")
        TEXT("{\"id\":\"salon_paris\",\"pivot_cm\":[7500,-29720,3255],\"yaw\":-90,\"watch_cm\":[7500,-30150,3015],\"watch_yaw\":90,\"scale\":1.4},")
        TEXT("{\"id\":\"salon_bar\",\"pivot_cm\":[5750,-31637.6,3305],\"yaw\":90,\"watch_cm\":[5750,-31160,3015],\"watch_yaw\":-90,\"scale\":1.3}]}");
    if (!TestTrue(TEXT("ParseSpots accepts building-derived runtime JSON"), RacingTv::ParseSpots(CustomJson, Parsed, &Error) && Parsed.Num() == 4))
        return false;
    TestTrue(TEXT("ParseSpots updates pivot and yaw"), Parsed[0].Pivot.Equals(FVector(-2500., -100., 248.), .01) && FMath::IsNearlyEqual(Parsed[0].Yaw, 175.f));
    TestFalse(TEXT("ParseSpots rejects incomplete spots without fallback"), RacingTv::ParseSpots(TEXT("{\"tv_spots\":[]}"), Parsed, &Error));
    TestTrue(TEXT("Rejected ParseSpots clears output"), Parsed.IsEmpty() && !Error.IsEmpty());
    TestFalse(TEXT("ParseSpots rejects missing tv_spots key"), RacingTv::ParseSpots(TEXT("{\"version\":1}"), Parsed, &Error));
    TestFalse(TEXT("LoadSpots rejects missing file without fallback"), RacingTv::LoadSpots(TEXT("/nonexistent/belmonte/runtime.json"), Parsed, &Error) || !Parsed.IsEmpty());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingSharedHorseGaitTest, "Yorimichi.Racing.SharedHorseGait",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingSharedHorseGaitTest::RunTest(const FString&)
{
    TestEqual(TEXT("Idle below 12 cm/s"), UHorseComponent::GaitForSpeed(11.9f), 0);
    TestEqual(TEXT("Walk at 12 cm/s"), UHorseComponent::GaitForSpeed(12.f), 1);
    TestEqual(TEXT("Sprint at 1180 cm/s"), UHorseComponent::GaitForSpeed(1180.f), 5);
    // Mounted walk starts at 10 cm/s; racing starts at 12 cm/s and caps sprint at 1.45x.
    TestTrue(TEXT("Mounted walk at 10 cm/s is 0.82"), FMath::IsNearlyEqual(UHorseComponent::PlayRateForGait(1, 10.f, false), .82f, 1e-4f));
    TestTrue(TEXT("Mounted walk at 135 cm/s is midpoint"), UHorseComponent::PlayRateForGait(1, 135.f, false) > UHorseComponent::PlayRateForGait(1, 135.f, true));
    TestTrue(TEXT("Mounted sprint clamps at 1.22"), FMath::IsNearlyEqual(UHorseComponent::PlayRateForGait(5, 1800.f, false), 1.22f, 1e-4f));
    TestTrue(TEXT("Racing sprint clamps at 1.45"), FMath::IsNearlyEqual(UHorseComponent::PlayRateForGait(5, 1800.f, true), 1.45f, 1e-4f));
    TSharedPtr<FJsonObject> Breed;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(TEXT("{\"contacts\":{\"saddle_root\":[0.04,0.12,1.6],\"seat_z\":1.43}}"));
    TestTrue(TEXT("Breed JSON parses"), FJsonSerializer::Deserialize(Reader, Breed) && Breed.IsValid());
    FVector Saddle = FVector::ZeroVector;
    double SeatZ = 0.;
    TestTrue(TEXT("ReadSeatContacts succeeds"), UHorseComponent::ReadSeatContacts(Breed, Saddle, SeatZ));
    TestTrue(TEXT("ReadSeatContacts converts metres to cm and negates Y"), Saddle.Equals(FVector(4., -12., 160.), 1e-3) && FMath::IsNearlyEqual(SeatZ, 143., 1e-3));
    TSharedPtr<FJsonObject> Empty = MakeShared<FJsonObject>();
    TestFalse(TEXT("ReadSeatContacts rejects missing contacts"), UHorseComponent::ReadSeatContacts(Empty, Saddle, SeatZ));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingTvDirectorTest, "Yorimichi.Racing.TvDirector",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingTvDirectorTest::RunTest(const FString&)
{
    // The shot list on its own: the build-up, the start, the race, the line, the field pulling up.
    using RacingTv::EShot;
    auto Shot = [](double T, double Run, double FirstHome = 90., double LastHome = 95., bool bStraight = false)
    {
        return RacingTv::ChooseShot(T, Run, 1600., FirstHome, LastHome, bStraight);
    };
    TestTrue(TEXT("The course from above first"), Shot(-115., 0.) == EShot::Course);
    TestTrue(TEXT("Then the stand"), Shot(-105., 0.) == EShot::Stands);
    TestTrue(TEXT("The crowd"), Shot(-95., 0.) == EShot::Crowd);
    TestTrue(TEXT("The field lined up"), Shot(-85., 0.) == EShot::Lineup);
    TestTrue(TEXT("Round again"), Shot(-75., 0.) == EShot::Course);
    TestTrue(TEXT("Start"), Shot(-5., 0.) == EShot::Start && Shot(-14., 0.) == EShot::Start);
    TestTrue(TEXT("Travelling"), Shot(30., 500.) == EShot::Travelling);
    TestTrue(TEXT("From above in the second stage"), Shot(25., 400.) == EShot::Aerial);
    TestTrue(TEXT("and in the third"), Shot(55., 900.) == EShot::Aerial);
    TestTrue(TEXT("Face on the straight"), Shot(70., 1300., 90., 95., true) == EShot::Face);
    TestTrue(TEXT("Not before the straight"), Shot(60., 1150., 90., 95., true) == EShot::Travelling);
    TestTrue(TEXT("Line"), Shot(86., 1540., 90., 95., true) == EShot::Line);
    TestTrue(TEXT("Line until the last is home"), Shot(98., 1640.) == EShot::Line);
    TestTrue(TEXT("Finish"), Shot(100., 1660.) == EShot::Finish);

    // A real race at Belmonte: the camera is the same for the same clock (every player sees one picture), the shots come in
    // order and never go back, and the field is in front of the camera and in frame.
    RacingTest::FRaceFixture Fixture;
    if (!Fixture.Make(*this)) return false;
    ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
    FString Error;
    const bool bLoaded = Service->LoadBelmonteCourses(RacingTest::CoursesJson(), RacingTest::BelmonteOrigin, Error);
    if (!TestTrue(TEXT("The courses parse: ") + Error, bLoaded)) return false;
    FRacingNetRace Race = Fixture.Snapshot.Race;
    Race.Venue = uint8(ERacingVenue::Belmonte);
    Race.Track = 0;
    // A player in the stand's last third: the crowd shot frames that part of it.
    const RacingTv::FVenueShots& Venue = RacingTv::VenueShots(Race.Venue);
    const FRacingCourse& Course = *Service->GetCourse(ERacingVenue::Belmonte, 0);
    const TArray<FVector> Players = {Course.At(Venue.StandS + Venue.StandHalf * .6, Venue.StandOut + 4.)};
    TestEqual(TEXT("The crowd camera finds the player"), RacingTv::CrowdCamera(Course, Venue, Players), 2);
    TestEqual(TEXT("The middle one with nobody there"), RacingTv::CrowdCamera(Course, Venue, {}), 1);
    TArray<EShot> Seen;
    int32 Framed = 0, Samples = 0;
    for (double T = -RacingTv::WindowSeconds + 1.; T <= HRClock::RaceSeconds; T += .5)
    {
        RacingTv::FCamera A, B;
        if (!TestTrue(TEXT("A camera"), RacingTv::Direct(*Service, Race, Race.Start + T, Players, A))) return false;
        RacingTv::Direct(*Service, Race, Race.Start + T, Players, B);
        if (!(A.Eye == B.Eye && A.Aim == B.Aim && A.Fov == B.Fov && A.Shot == B.Shot)) { AddError(FString::Printf(TEXT("Not deterministic at t=%.1f"), T)); return false; }
        if (Seen.IsEmpty() || Seen.Last() != A.Shot)
        {
            // From the start on, the race goes forward: never back to the start, nor from the line to the race.
            if (!Seen.IsEmpty() && T > 0. && (A.Shot == EShot::Start || (uint8(Seen.Last()) >= uint8(EShot::Line) && uint8(A.Shot) < uint8(Seen.Last()))))
                AddError(FString::Printf(TEXT("Back from %s to %s at t=%.1f"), RacingTv::ShotName(Seen.Last()), RacingTv::ShotName(A.Shot), T));
            Seen.Add(A.Shot);
        }
        TestTrue(TEXT("A sane field of view"), A.Fov >= 4.f && A.Fov <= 90.f);
        // The leader in front of the camera, inside the frame.
        int32 Leader = 0;
        double Lead = -1e9;
        for (int32 I = 0; I < Race.Runners.Num(); ++I)
        {
            const double D = RacingMotion::Distance(Race.Runners[I].Plan(Race.Distance), T);
            if (D > Lead) { Lead = D; Leader = I; }
        }
        FVector Where;
        float Yaw = 0.f;
        double Speed = 0.;
        Service->RunnerAt(Race, Leader, Race.Start + T, Where, Yaw, Speed);
        const FVector L = (A.Aim - A.Eye).Rotation().UnrotateVector(Where + FVector(0., 0., 130.) - A.Eye);
        // The leader is filmed during the race (the build-up films the stands and the paddock too).
        if (T < 6. || A.Shot == EShot::Aerial) continue;
        ++Samples;
        if (L.X > 0. && FMath::RadiansToDegrees(FMath::Atan(FMath::Abs(L.Y) / L.X)) <= A.Fov * .5f) ++Framed;
    }
    FString Order;
    for (const EShot S : Seen) Order += FString(Order.IsEmpty() ? TEXT("") : TEXT(" > ")) + RacingTv::ShotName(S);
    AddInfo(TEXT("Shots: ") + Order);
    for (const EShot S : {EShot::Course, EShot::Stands, EShot::Crowd, EShot::Lineup, EShot::Start, EShot::Travelling, EShot::Aerial, EShot::Line, EShot::Finish})
        TestTrue(FString::Printf(TEXT("The %s shot is used: %s"), RacingTv::ShotName(S), *Order), Seen.Contains(S));
    // The leader is always in frame but for the line (fixed on the post, the field enters it) and the pull-up (the group).
    TestTrue(FString::Printf(TEXT("The leader is in frame most of the time (%d of %d)"), Framed, Samples), Framed >= Samples * 3 / 4);
    return true;
}
// ------------------------------------------------------------------------------------------------------------ betting

namespace RacingTest
{
    /** A fresh world one minute before its first race, with players p0..p<Count-1>; the race and its start. */
    struct FBetFixture
    {
        FHRWorldState World;
        const FHRRace* Race = nullptr;
        FString Key;
        double Start = 0.;
        bool Make(FAutomationTestBase& Test, int32 Players)
        {
            World = HRRules::CreateWorld(TEXT("yorimichi-betting-test"));
            HRRules::StartClock(World, 1700000000);
            for (const FHRRace& R : World.Meeting.Races)
                if (R.Status == TEXT("declared") && R.Entries.Num() >= 2) { Race = &R; break; }
            if (!Test.TestNotNull(TEXT("The day has a race to bet on"), Race)) return false;
            Key = Race->Key;
            Start = HRRules::RaceStartSeconds(World, Key);
            for (int32 I = 0; I < Players; ++I) HRRules::AddPlayer(World, FString::Printf(TEXT("p%d"), I), FString::Printf(TEXT("Player %d"), I));
            return true;
        }
        const FHRRace& Find() const { return *HRRules::FindRace(World, Key); }
        /** Another declared race of the day. */
        const FHRRace* Other() const
        {
            for (const FHRRace& R : World.Meeting.Races)
                if (R.Key != Key && R.Status == TEXT("declared") && R.Entries.Num() >= 2) return &R;
            return nullptr;
        }
    };

    FString TempSave()
    {
        return FPaths::ConvertRelativePathToFull(FPaths::AutomationTransientDir() / FString::Printf(TEXT("racing-bets-%s/world.json"),
            *FGuid::NewGuid().ToString(EGuidFormats::Digits)));
    }

    template <typename T> T OverTheWire(const T& Value)
    {
        TArray<uint8> Bytes;
        FMemoryWriter Writer(Bytes);
        T::StaticStruct()->SerializeBin(Writer, const_cast<T*>(&Value));
        T Received;
        FMemoryReader Reader(Bytes);
        T::StaticStruct()->SerializeBin(Reader, &Received);
        return Received;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingBetValidationTest, "Yorimichi.Racing.BetValidation",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingBetValidationTest::RunTest(const FString&)
{
    RacingTest::FBetFixture F;
    if (!F.Make(*this, 3)) return false;
    using L = HRRules::FBetLimits;
    const double Before = F.Start - 60.;
    const FString Horse = F.Find().Entries[0].HorseId;
    const int32 Coins = HRRules::FindPlayer(F.World, TEXT("p0"))->Coins;
    auto Refused = [&](const TCHAR* What, const FString& Player, const FString& Race, const FString& Id, int32 Stake, double Now, const TCHAR* Expect)
    {
        const int32 Tickets = F.World.Tickets.Num();
        const FString Error = ARacingService::PlaceBetIn(F.World, Player, Race, Id, Stake, Now);
        TestTrue(FString::Printf(TEXT("%s is refused (%s)"), What, *Error), Error.Contains(Expect));
        TestEqual(FString::Printf(TEXT("%s leaves no ticket"), What), F.World.Tickets.Num(), Tickets);
    };
    Refused(TEXT("An unknown player"), TEXT("nobody"), F.Key, Horse, 5, Before, TEXT("portefeuille"));
    Refused(TEXT("A race not on today's card"), TEXT("p0"), TEXT("village:99"), Horse, 5, Before, TEXT("programme"));
    Refused(TEXT("A horse not in the race"), TEXT("p0"), F.Key, TEXT("horse:none"), 5, Before, TEXT("partant"));
    Refused(TEXT("A stake under the minimum"), TEXT("p0"), F.Key, Horse, L::MinStake - 1, Before, TEXT("La mise va de"));
    Refused(TEXT("A stake over the maximum"), TEXT("p0"), F.Key, Horse, L::MaxStake + 1, Before, TEXT("La mise va de"));
    Refused(TEXT("A bet at the start"), TEXT("p0"), F.Key, Horse, 5, F.Start, TEXT("fermés"));
    Refused(TEXT("A bet after the start"), TEXT("p0"), F.Key, Horse, 5, F.Start + 1., TEXT("fermés"));
    Refused(TEXT("A bet at a non-finite time"), TEXT("p0"), F.Key, Horse, 5, std::numeric_limits<double>::quiet_NaN(), TEXT("fermés"));

    TestEqual(TEXT("A valid bet is taken"), ARacingService::PlaceBetIn(F.World, TEXT("p0"), F.Key, Horse, 5, Before), FString());
    TestEqual(TEXT("and paid from the wallet"), HRRules::FindPlayer(F.World, TEXT("p0"))->Coins, Coins - 5);
    TestEqual(TEXT("One open ticket"), F.World.Tickets.Num(), 1);
    // Three tickets a race.
    ARacingService::PlaceBetIn(F.World, TEXT("p0"), F.Key, Horse, 1, Before);
    ARacingService::PlaceBetIn(F.World, TEXT("p0"), F.Key, Horse, 1, Before);
    Refused(TEXT("A fourth ticket on one race"), TEXT("p0"), F.Key, Horse, 1, Before, TEXT("tickets par course"));
    // The day's limit.
    for (int32 I = 0; I < 3; ++I) ARacingService::PlaceBetIn(F.World, TEXT("p1"), F.Key, Horse, L::MaxStake, Before);
    TestEqual(TEXT("p1 staked the day's limit"), HRRules::DayStake(F.World, TEXT("p1")), L::PerDay);
    if (const FHRRace* Other = F.Other())
        Refused(TEXT("A bet over the day's limit"), TEXT("p1"), Other->Key, Other->Entries[0].HorseId, 1, Before, TEXT("par jour"));
    // The balance.
    HRRules::FindPlayer(F.World, TEXT("p2"))->Coins = 3;
    Refused(TEXT("A stake over the balance"), TEXT("p2"), F.Key, Horse, 5, Before, TEXT("Solde insuffisant"));
    TestEqual(TEXT("Exactly the balance is fine"), ARacingService::PlaceBetIn(F.World, TEXT("p2"), F.Key, Horse, 3, Before), FString());
    TestEqual(TEXT("down to zero"), HRRules::FindPlayer(F.World, TEXT("p2"))->Coins, 0);

    // The card: the race open, its runners' odds, the player's tickets on it; nothing once it has started.
    FRacingCard Card;
    ARacingService::BuildCard(F.World, TEXT("p0"), Before, Card);
    const FRacingCardRace* Open = Card.Races.FindByPredicate([&F](const FRacingCardRace& R) { return R.Key == F.Key; });
    if (TestNotNull(TEXT("The card has the race"), Open))
    {
        TestEqual(TEXT("All its runners"), Open->Runners.Num(), F.Find().Entries.Num());
        TestEqual(TEXT("p0's three tickets"), int32(Open->MyTickets), 3);
        for (const FRacingCardRunner& R : Open->Runners)
            TestTrue(TEXT("Odds of at least the rules' minimum"), R.OddsHundredths >= int32(HRRules::MinRapport * 100.) - 1);
    }
    for (int32 I = 1; I < Card.Races.Num(); ++I) TestTrue(TEXT("Soonest first"), Card.Races[I - 1].Start <= Card.Races[I].Start);
    ARacingService::BuildCard(F.World, TEXT("p0"), F.Start, Card);
    TestFalse(TEXT("A started race is off the card"), Card.Races.ContainsByPredicate([&F](const FRacingCardRace& R) { return R.Key == F.Key; }));
    TestTrue(TEXT("The card survives the wire"), RacingTest::OverTheWire(Card) == Card);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingBetSettlementTest, "Yorimichi.Racing.BetSettlement",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingBetSettlementTest::RunTest(const FString&)
{
    // One player on each runner, all near the coin ceiling: exactly one wins, at the rules' odds, saturated at MaxCoins.
    RacingTest::FBetFixture F;
    if (!F.Make(*this, HRRules::MaxRunners)) return false;
    const TArray<FHRRunner> Entries = F.Find().Entries;
    const int32 Stake = HRRules::FBetLimits::MaxStake;
    for (int32 I = 0; I < Entries.Num(); ++I)
    {
        const FString Id = FString::Printf(TEXT("p%d"), I);
        HRRules::FindPlayer(F.World, Id)->Coins = I == 0 ? HRRules::MaxCoins : 100;
        TestEqual(TEXT("Each bet is taken"), ARacingService::PlaceBetIn(F.World, Id, F.Key, Entries[I].HorseId, Stake, F.Start - 30.), FString());
    }
    // The rules run and settle the race at its start.
    HRRules::AdvanceTo(F.World, F.Start + 1.);
    const FHRRace& Race = F.Find();
    if (!TestTrue(TEXT("The race is run"), Race.Status == TEXT("run") && Race.Finishes.Num() >= 2)) return false;
    const FString Winner = Race.Finishes[0].HorseId;
    const double Home = F.Start + Race.Finishes[0].TimeUs / 1e6;
    int32 Won = 0;
    for (int32 I = 0; I < Entries.Num(); ++I)
    {
        const FString Id = FString::Printf(TEXT("p%d"), I);
        const FHRPlayer& P = *HRRules::FindPlayer(F.World, Id);
        const FHRTicket* T = F.World.Tickets.FindByPredicate([&Id](const FHRTicket& X) { return X.PlayerId == Id; });
        if (!TestNotNull(TEXT("A ticket"), T)) return false;
        const int64 Before = (I == 0 ? int64(HRRules::MaxCoins) : 100) - Stake;
        // Before the winner is home the wallet shows the ticket running and the coins without the payout.
        FRacingWalletView Running, Seen;
        ARacingService::BuildWallet(F.World, Id, F.Start + 1., Running);
        TestTrue(TEXT("Still running on screen"), Running.Tickets.Num() && Running.Tickets[0].GetStatus() == ERacingTicket::Open);
        TestEqual(TEXT("No payout shown yet"), int64(Running.Coins), FMath::Clamp<int64>(int64(P.Coins) - T->Payout, 0, HRRules::MaxCoins));
        ARacingService::BuildWallet(F.World, Id, Home + ARacingService::RevealSeconds + .1, Seen);
        TestEqual(TEXT("The wallet shows the coins once the winner is home"), Seen.Coins, P.Coins);
        if (Entries[I].HorseId == Winner)
        {
            ++Won;
            TestEqual(TEXT("The winning ticket is won"), T->Status, FString(TEXT("won")));
            TestTrue(TEXT("at no less than the rules' lowest odds"), T->Rapport >= HRRules::MinRapport);
            TestEqual(TEXT("paid stake times odds"), T->Payout, int32(FMath::FloorToDouble(Stake * T->Rapport)));
            TestEqual(TEXT("credited, saturated at MaxCoins"), int64(P.Coins), FMath::Min<int64>(Before + T->Payout, HRRules::MaxCoins));
            TestTrue(TEXT("Shown won"), Seen.Tickets[0].GetStatus() == ERacingTicket::Won);
        }
        else
        {
            TestEqual(TEXT("A losing ticket is lost"), T->Status, FString(TEXT("lost")));
            TestEqual(TEXT("and pays nothing"), int64(P.Coins), Before);
            TestTrue(TEXT("Shown lost"), Seen.Tickets[0].GetStatus() == ERacingTicket::Lost);
        }
        TestTrue(TEXT("No balance over MaxCoins"), P.Coins >= 0 && P.Coins <= HRRules::MaxCoins);
    }
    TestEqual(TEXT("Exactly one winner"), Won, 1);
    // Settling again (the day's close does) pays nothing twice.
    TArray<int32> Coins;
    for (const TPair<FString, FHRPlayer>& P : F.World.Players) Coins.Add(P.Value.Coins);
    HRRules::SettleRace(F.World, Race);
    int32 I = 0;
    for (const TPair<FString, FHRPlayer>& P : F.World.Players) TestEqual(TEXT("Settled once"), P.Value.Coins, Coins[I++]);
    TestEqual(TEXT("Credit saturates"), HRRules::Credit(HRRules::MaxCoins - 1, 1000), HRRules::MaxCoins);
    TestEqual(TEXT("A negative credit adds nothing"), HRRules::Credit(10, -5), 10);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingBetRefundTest, "Yorimichi.Racing.BetRefund",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingBetRefundTest::RunTest(const FString&)
{
    // A race that does not take place refunds its tickets, before any payout, and the wallet shows them refunded.
    RacingTest::FBetFixture F;
    if (!F.Make(*this, 2)) return false;
    const FString Horse = F.Find().Entries[0].HorseId;
    const int32 Coins = HRRules::FindPlayer(F.World, TEXT("p0"))->Coins;
    TestEqual(TEXT("A bet"), ARacingService::PlaceBetIn(F.World, TEXT("p0"), F.Key, Horse, 7, F.Start - 30.), FString());
    FHRRace* Race = HRRules::FindRace(F.World, F.Key);
    // Still declared: settling does nothing (no outcome yet).
    HRRules::SettleRace(F.World, *Race);
    TestEqual(TEXT("An undecided race keeps its tickets open"), F.World.Tickets[0].Status, FString(TEXT("open")));
    Race->Status = TEXT("uncontested");
    HRRules::SettleRace(F.World, *Race);
    TestEqual(TEXT("Refunded"), F.World.Tickets[0].Status, FString(TEXT("refunded")));
    TestEqual(TEXT("The stake comes back"), HRRules::FindPlayer(F.World, TEXT("p0"))->Coins, Coins);
    FRacingWalletView View;
    ARacingService::BuildWallet(F.World, TEXT("p0"), F.Start + ARacingService::RevealSeconds + 1., View);
    if (TestEqual(TEXT("One ticket"), View.Tickets.Num(), 1))
    {
        TestTrue(TEXT("Shown refunded"), View.Tickets[0].GetStatus() == ERacingTicket::Refunded);
        TestEqual(TEXT("with the stake"), View.Tickets[0].Payout, 7);
    }
    TestEqual(TEXT("The wallet has it back"), View.Coins, Coins);
    // A declared horse that does not run: refunded, while the others are settled at odds without it.
    RacingTest::FBetFixture G;
    if (!G.Make(*this, 2)) return false;
    const TArray<FHRRunner> Entries = G.Find().Entries;
    ARacingService::PlaceBetIn(G.World, TEXT("p0"), G.Key, Entries[0].HorseId, 4, G.Start - 30.);
    ARacingService::PlaceBetIn(G.World, TEXT("p1"), G.Key, Entries[1].HorseId, 4, G.Start - 30.);
    FHRRace Ran = G.Find();
    HRRules::ResolveRace(G.World, Ran);
    Ran.Finishes.RemoveAll([&Entries](const FHRFinish& X) { return X.HorseId == Entries[0].HorseId; });
    if (Ran.Finishes.Num() < 2) return true;   // a two-horse field: nothing more to see
    HRRules::SettleRace(G.World, Ran);
    TestEqual(TEXT("The non-runner's ticket is refunded"), G.World.Tickets[0].Status, FString(TEXT("refunded")));
    TestTrue(TEXT("The other is settled"), G.World.Tickets[1].Status == TEXT("won") || G.World.Tickets[1].Status == TEXT("lost"));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingBetPersistenceTest, "Yorimichi.Racing.BetPersistence",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingBetPersistenceTest::RunTest(const FString&)
{
    // The host's player keeps its wallet and tickets in the racing save; a guest's session wallet is never written.
    const FString Path = RacingTest::TempSave();
    ARacingService* Host = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("A world"), Host->OpenWorld(Path, TEXT("bet-save-test")))) return false;
    TestTrue(TEXT("The host's player"), Host->RegisterPlayer(TEXT("local:persist"), TEXT("Paul")));
    TestTrue(TEXT("A guest for this session"), Host->RegisterPlayer(TEXT("session:0123"), TEXT("Henry")));
    const double Now = Host->HostWorldSeconds();
    const FHRRace* Race = nullptr;
    for (const FHRRace& R : Host->GetWorldState().Meeting.Races)
        if (!R.IsRun() && R.Entries.Num() >= 2 && HRRules::RaceStartSeconds(Host->GetWorldState(), R.Key) > Now + 5.) { Race = &R; break; }
    if (!TestNotNull(TEXT("A race ahead"), Race)) return false;
    const FString Key = Race->Key, Horse = Race->Entries[1].HorseId;
    TestEqual(TEXT("The host's bet"), Host->PlaceBet(TEXT("local:persist"), Key, Horse, 6), FString());
    TestEqual(TEXT("The guest's bet"), Host->PlaceBet(TEXT("session:0123"), Key, Horse, 2), FString());
    const int32 Coins = HRRules::FindPlayer(Host->GetWorldState(), TEXT("local:persist"))->Coins;
    TestTrue(TEXT("Saved"), Host->SaveNow());
    FString Text;
    FFileHelper::LoadFileToString(Text, *Path);
    TestFalse(TEXT("No session player in the file"), Text.Contains(TEXT("session:")));
    FHRWorldState Admitted;
    FString Error;
    TestTrue(TEXT("The file is an admissible world: ") + Error, HRSave::FromJson(Text, Admitted, Error));
    TestTrue(TEXT("The guest still has its wallet in this session"), HRRules::FindPlayer(Host->GetWorldState(), TEXT("session:0123")) != nullptr);

    ARacingService* Reloaded = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("Reloaded"), Reloaded->OpenWorld(Path, TEXT("another-seed")))) return false;
    const FHRWorldState& S = Reloaded->GetWorldState();
    const FHRPlayer* Player = HRRules::FindPlayer(S, TEXT("local:persist"));
    if (TestNotNull(TEXT("The host's player is back"), Player)) TestEqual(TEXT("with its coins"), Player->Coins, Coins);
    TestNull(TEXT("The guest is not"), HRRules::FindPlayer(S, TEXT("session:0123")));
    TestEqual(TEXT("One ticket kept"), S.Tickets.Num(), 1);
    FRacingWalletView View;
    ARacingService::BuildWallet(S, TEXT("local:persist"), Now, View);
    TestTrue(TEXT("The reloaded wallet shows the open bet"), View.bActive && View.OpenCount() == 1 && View.Tickets[0].Stake == 6);
    TestFalse(TEXT("A saved player is not a session one"), View.bSession);
    ARacingService::BuildWallet(Host->GetWorldState(), TEXT("session:0123"), Now, View);
    TestTrue(TEXT("The guest's wallet says it is for this session"), View.bSession);
    IFileManager::Get().DeleteDirectory(*FPaths::GetPath(Path), false, true);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingBetRequestTest, "Yorimichi.Racing.BetRequest",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingBetRequestTest::RunTest(const FString&)
{
    // A guest's bet as it travels: the request over the wire to the host, its answer back, then the wallet replicated
    // to its owner; the result line when the race is decided and seen.
    {
        // As the net driver does before it asks: the class's replicated properties get their indices first.
        URacingWallet::StaticClass()->SetUpRuntimeReplicationData();
        TArray<FLifetimeProperty> Props;
        GetDefault<URacingWallet>()->GetLifetimeReplicatedProps(Props);
        int32 OwnerOnly = 0;
        for (const FName Name : {FName(TEXT("View")), FName(TEXT("Card"))})
        {
            const FProperty* Property = URacingWallet::StaticClass()->FindPropertyByName(Name);
            if (!TestNotNull(TEXT("A replicated property"), Property)) return false;
            for (const FLifetimeProperty& P : Props)
                if (P.RepIndex == Property->RepIndex) OwnerOnly += P.Condition == COND_OwnerOnly ? 1 : 0;
        }
        TestEqual(TEXT("The wallet and the card replicate to their owner only"), OwnerOnly, 2);
    }
    const FString Path = RacingTest::TempSave();
    ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("A world"), Service->OpenWorld(Path, TEXT("bet-request-test")))) return false;
    const FString Guest(TEXT("session:feed"));
    Service->RegisterPlayer(Guest, TEXT("Guest"));
    const double Now = Service->HostWorldSeconds();
    const FHRRace* Race = nullptr;
    for (const FHRRace& R : Service->GetWorldState().Meeting.Races)
        if (!R.IsRun() && R.Entries.Num() >= 2 && HRRules::RaceStartSeconds(Service->GetWorldState(), R.Key) > Now + 5.) { Race = &R; break; }
    if (!TestNotNull(TEXT("A race ahead"), Race)) return false;
    const FString Key = Race->Key, Horse = Race->Entries[0].HorseId;
    const double Start = HRRules::RaceStartSeconds(Service->GetWorldState(), Key);

    URacingWallet* OnHost = NewObject<URacingWallet>(GetTransientPackage());
    URacingWallet* OnClient = NewObject<URacingWallet>(GetTransientPackage());
    OnHost->HostPlayerId = Guest;
    auto Round = [&](const FRacingBetRequest& Request)
    {
        const FString Error = OnHost->HostHandle(RacingTest::OverTheWire(Request), Service);
        OnClient->ApplyReply(Request.Seq, Error);
        FRacingWalletView View;
        ARacingService::BuildWallet(Service->GetWorldState(), Guest, Service->HostWorldSeconds(), View);
        OnHost->HostSetView(View);
        OnClient->ApplyReplicatedView(RacingTest::OverTheWire(OnHost->GetView()));
        return Error;
    };
    FRacingBetRequest Request;
    Request.Seq = 1;
    Request.RaceKey = Key;
    Request.HorseId = Horse;
    Request.Stake = 4;
    const int32 Coins = HRRules::FindPlayer(Service->GetWorldState(), Guest)->Coins;
    TestEqual(TEXT("The host takes the bet"), Round(Request), FString());
    TestTrue(TEXT("The client hears so"), OnClient->GetReplySeq() == 1u);
    TestTrue(TEXT("with no refusal"), OnClient->GetReplyError().IsEmpty());
    TestEqual(TEXT("Its wallet arrives"), OnClient->GetView().Coins, Coins - 4);
    TestEqual(TEXT("with the open ticket"), OnClient->GetView().OpenCount(), 1);

    Request.Seq = 2;
    Request.HorseId = TEXT("horse:none");
    TestTrue(TEXT("A horse not running is refused"), Round(Request).Contains(TEXT("partant")));
    TestTrue(TEXT("and the client hears why"), OnClient->GetReplySeq() == 2u && OnClient->GetReplyError().Contains(TEXT("partant")));
    Request.Seq = 3;
    Request.HorseId = FString::ChrN(HRSave::MaxIdChars + 1, TEXT('x'));
    TestTrue(TEXT("An oversized request is refused before the rules"), Round(Request).Contains(TEXT("valable")));
    Request.Seq = 4;
    Request.HorseId = Horse;
    Request.Stake = 1000;
    TestTrue(TEXT("A stake over the limit is refused"), Round(Request).Contains(TEXT("mise")));
    TestEqual(TEXT("Refusals cost nothing"), OnClient->GetView().Coins, Coins - 4);
    float Alpha = 0.f;
    TestTrue(TEXT("No result line yet"), OnClient->GetToast(Alpha).IsEmpty());

    // The race starts (betting closes), is decided, and is seen won or lost.
    Service->AdvanceClock(Start - Service->HostWorldSeconds() + .5);
    Request.Seq = 5;
    Request.Stake = 1;
    TestTrue(TEXT("Betting is closed at the start"), Round(Request).Contains(TEXT("fermés")));
    TestEqual(TEXT("The ticket still runs on screen"), OnClient->GetView().OpenCount(), 1);
    const FHRRace* Run = HRRules::FindRace(Service->GetWorldState(), Key);
    const double Home = Run && Run->Finishes.Num() ? Run->Finishes[0].TimeUs / 1e6 : 0.;
    Service->AdvanceClock(Home + ARacingService::RevealSeconds + 1.);
    FRacingWalletView View;
    ARacingService::BuildWallet(Service->GetWorldState(), Guest, Service->HostWorldSeconds(), View);
    OnHost->HostSetView(View);
    OnClient->ApplyReplicatedView(RacingTest::OverTheWire(OnHost->GetView()));
    TestEqual(TEXT("The ticket is settled"), OnClient->GetView().OpenCount(), 0);
    const FString Line = OnClient->GetToast(Alpha);
    TestTrue(TEXT("The owner gets a result line: ") + Line, Line.StartsWith(TEXT("Pari ")));
    TestEqual(TEXT("The client's coins are the host's"), OnClient->GetView().Coins, HRRules::FindPlayer(Service->GetWorldState(), Guest)->Coins);
    IFileManager::Get().DeleteDirectory(*FPaths::GetPath(Path), false, true);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingBetPreviewTest, "Yorimichi.Racing.BetPreview",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingBetPreviewTest::RunTest(const FString&)
{
    // Tomorrow's meeting as the rules will open it, from a copy: the world itself is untouched.
    RacingTest::FBetFixture F;
    if (!F.Make(*this, 1)) return false;
    const FString Before = HRSave::ToJson(F.World);
    FRacingCardPreview Preview;
    ARacingService::BuildPreview(F.World, Preview);
    TestEqual(TEXT("The world is untouched"), HRSave::ToJson(F.World), Before);
    TestEqual(TEXT("The next day"), Preview.Day, F.World.T + 1);
    TestEqual(TEXT("at its venue"), int32(Preview.Venue), int32(ARacingService::VenueForDay(F.World.T + 1)));
    TestEqual(TEXT("its event"), Preview.Event, FString(HRContent::EventForT(F.World.T + 1).Name));
    // The same as the day the rules actually open.
    FHRWorldState Tomorrow = F.World;
    HRRules::AdvanceTo(Tomorrow, HRClock::DayStart(F.World.T + 1) + 1.);
    int32 Races = 0;
    double First = -1.;
    for (const FHRRace& R : Tomorrow.Meeting.Races)
    {
        const double Start = HRRules::RaceStartSeconds(Tomorrow, R.Key);
        if (Start < 0. || R.Entries.Num() < 2) continue;
        ++Races;
        if (First < 0. || Start < First) First = Start;
    }
    TestTrue(TEXT("Races are planned"), Preview.Races > 0);
    TestEqual(TEXT("as many as the day opens with"), Preview.Races, Races);
    TestEqual(TEXT("the first at the same time"), Preview.FirstStart, First);
    TestTrue(TEXT("in the next day"), Preview.FirstStart >= HRClock::DayStart(F.World.T + 1));
    FRacingCard Card;
    ARacingService::BuildCard(F.World, TEXT("p0"), F.Start - 10., Card);
    Card.Next = Preview;
    TestTrue(TEXT("The card with its preview survives the wire"), RacingTest::OverTheWire(Card) == Card);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingJsonEscapeTest, "Yorimichi.Racing.JsonEscape",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingJsonEscapeTest::RunTest(const FString&)
{
    // Horse names reach the HUD and live views as hand-built JSON: an apostrophe must stay a plain character.
    const FString Name = TEXT("Capella d'Aragon \"la \\ Grande\"\n\tdu\r\x01 Val");
    TestFalse(TEXT("Apostrophe is not escaped"), RacingJsonEscape(Name).Contains(TEXT("\\'")));
    const FString Text = FString::Printf(TEXT("{\"horse\":\"%s\"}"), *RacingJsonEscape(Name));
    TSharedPtr<FJsonObject> Obj;
    if (!TestTrue(TEXT("Parses"), FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Obj) && Obj.IsValid())) return false;
    TestEqual(TEXT("Round-trips"), Obj->GetStringField(TEXT("horse")), Name);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingCounterPlaceTest, "Yorimichi.Racing.CounterPlace",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingCounterPlaceTest::RunTest(const FString&)
{
    // The counter comes from runtime.json's racing_places (derived from the Salon hall's committed placement), never a
    // hardcoded spot: a missing or broken entry leaves no counter.
    const FString Json = TEXT("{\"version\":1,\"racing_places\":{\"counter\":{\"at_cm\":[100,200,30],\"yaw\":90,")
        TEXT("\"half_length_cm\":380,\"reach_cm\":260,\"behind_cm\":150,\"below_cm\":80,\"above_cm\":260}}}");
    RacingCounter::FCounter C;
    if (!TestTrue(TEXT("Parses the counter"), RacingCounter::Parse(RacingPlaces::Parse(Json), C))) return false;
    TestEqual(TEXT("Spot"), C.Spot, FVector(100., 200., 30.));
    TestEqual(TEXT("Yaw"), C.Yaw, 90.f);
    const FVector Origin(1000., -2000., 500.);
    // Facing +Y (yaw 90): the player stands in front (lower Y), the counter is along X.
    TestTrue(TEXT("At the spot"), RacingCounter::InReach(Origin + C.Spot, Origin, C));
    TestTrue(TEXT("In front, within reach"), RacingCounter::InReach(Origin + C.Spot + FVector(0., -250., 0.), Origin, C));
    TestFalse(TEXT("Too far in front"), RacingCounter::InReach(Origin + C.Spot + FVector(0., -270., 0.), Origin, C));
    TestTrue(TEXT("Along the counter"), RacingCounter::InReach(Origin + C.Spot + FVector(370., 0., 0.), Origin, C));
    TestFalse(TEXT("Past its end"), RacingCounter::InReach(Origin + C.Spot + FVector(390., 0., 0.), Origin, C));
    TestFalse(TEXT("Behind the counter"), RacingCounter::InReach(Origin + C.Spot + FVector(0., 160., 0.), Origin, C));
    TestFalse(TEXT("A floor below"), RacingCounter::InReach(Origin + C.Spot + FVector(0., 0., -100.), Origin, C));
    TestFalse(TEXT("No racing_places"), RacingCounter::Parse(RacingPlaces::Parse(TEXT("{\"version\":1}")), C));
    TestFalse(TEXT("Not JSON"), RacingCounter::Parse(RacingPlaces::Parse(TEXT("{")), C));
    const FString Bad = Json.Replace(TEXT("\"reach_cm\":260"), TEXT("\"reach_cm\":0"));
    TestFalse(TEXT("A zero extent"), RacingCounter::Parse(RacingPlaces::Parse(Bad), C));
    const FString Short = Json.Replace(TEXT("[100,200,30]"), TEXT("[100,200]"));
    TestFalse(TEXT("A short spot"), RacingCounter::Parse(RacingPlaces::Parse(Short), C));
    return true;
}
#endif
