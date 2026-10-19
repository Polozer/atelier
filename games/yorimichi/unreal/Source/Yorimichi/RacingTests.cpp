#include "RacingService.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "AtelierData.h"
#include "HRClock.h"
#include "HRRules.h"
#include "HRSave.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"
#include "Serialization/MemoryReader.h"
#include "Serialization/MemoryWriter.h"

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

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingBelmonteCourseTest, "Yorimichi.Racing.BelmonteCourse",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingBelmonteCourseTest::RunTest(const FString&)
{
    const FString Json = RacingTest::CoursesJson();
    if (!TestFalse(TEXT("belmonte_courses.json is readable"), Json.IsEmpty())) return false;
    ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
    FString Error;
    if (!TestTrue(TEXT("The courses parse: ") + Error, Service->LoadBelmonteCourses(Json, RacingTest::BelmonteOrigin, Error))) return false;
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
#endif
