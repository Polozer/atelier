#include "JapanMusic.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "WandererCharacter.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Misc/ScopeExit.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FJapanMusicTrainSceneTest, "Yorimichi.Music.TrainScene",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// A passenger aboard the Belmonte train, seated or standing (sitting boards the rider: both are bTrainAboard and not
// stepping through a door), hears the train pool: exactly Paul's four clips, whatever the zone.
bool FJapanMusicTrainSceneTest::RunTest(const FString&)
{
    UWorld* TestWorld = nullptr;
    for (const FWorldContext& Context : GEngine->GetWorldContexts())
        if (Context.World() && Context.World()->IsGameWorld()) { TestWorld = Context.World(); break; }
    if (!TestNotNull(TEXT("Music fixture uses a game world"), TestWorld)) return false;
    FActorSpawnParameters Spawn; Spawn.ObjectFlags |= RF_Transient; Spawn.bDeferConstruction = true;
    Spawn.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
    auto* Rider = TestWorld->SpawnActor<AWandererCharacter>(FVector(0., 0., 100000.), FRotator::ZeroRotator, Spawn);
    if (!TestNotNull(TEXT("Music fixture owns a real character"), Rider)) return false;
    ON_SCOPE_EXIT { Rider->bTrainAboard = false; Rider->AboardVehicle = ETransportVehicle::None; Rider->Destroy(); };

    TestTrue(TEXT("On foot: exploring"), FJapanMusicRules::ActivityScene(*Rider) == EJapanMusicScene::Explore);
    Rider->bTrainAboard = true; Rider->AboardVehicle = ETransportVehicle::Train;  // as the train service boards a rider
    TestTrue(TEXT("A train passenger is in the train scene"), FJapanMusicRules::ActivityScene(*Rider) == EJapanMusicScene::Train);
    TestEqual(TEXT("in any area"), FJapanMusicRules::PoolName(EJapanMusicScene::Train, TEXT("belmonte")), FString(TEXT("train")));
    TestEqual(TEXT("in the wild"), FJapanMusicRules::PoolName(EJapanMusicScene::Train, TEXT("wild")), FString(TEXT("train")));
    Rider->bTrainAboard = false; Rider->AboardVehicle = ETransportVehicle::None;
    TestTrue(TEXT("Off the train: exploring again"), FJapanMusicRules::ActivityScene(*Rider) == EJapanMusicScene::Explore);

    const TArray<FString> Clips = FJapanMusicRules::PoolClips(TEXT("train"));
    TestEqual(TEXT("The train pool is four clips"), Clips.Num(), 4);
    for (const TCHAR* Id : {TEXT("67c9760a-c69e-451c-b4db-dc61f2f9fc6e"), TEXT("508699d0-8143-4924-a11e-a1bdd60956de"),
                            TEXT("19fedb51-66cc-4ec8-91c0-a0201c47fe1d"), TEXT("055e7d39-0e67-48e1-93e8-838fc862dfbf")})
    {
        FJapanMusicTrack T; T.Id = Id; T.Group = TEXT("jazz_salon"); T.Role = TEXT("day");
        TestTrue(FString::Printf(TEXT("%s is in the train pool, in any zone"), Id),
            FJapanMusicRules::InPool(TEXT("train"), TEXT("belmonte"), T) && FJapanMusicRules::InPool(TEXT("train"), FString(), T));
    }
    // Another take of the same piece, or a group the zone pools use, is not.
    FJapanMusicTrack Other; Other.Id = TEXT("26cbde9f-48a4-42e3-af6e-6518b4d05eb4"); Other.Group = TEXT("jazz_harbor");
    TestFalse(TEXT("The other Harbor Lounge take stays out"), FJapanMusicRules::InPool(TEXT("train"), TEXT("belmonte"), Other));
    Other.Group = TEXT("belmonte"); Other.Role = TEXT("day");
    TestFalse(TEXT("The zone's own score stays out"), FJapanMusicRules::InPool(TEXT("train"), TEXT("belmonte"), Other));
    // The group pools are unchanged: the Belmonte pool still takes its jazz, the zeppelin keeps "air".
    Other.Group = TEXT("jazz_salon");
    TestTrue(TEXT("Group pools still match by group"), FJapanMusicRules::InPool(TEXT("belmonte"), TEXT("belmonte"), Other));
    TestEqual(TEXT("The zeppelin keeps its pool"), FJapanMusicRules::PoolName(EJapanMusicScene::Air, TEXT("belmonte")), FString(TEXT("air")));
    return true;
}
#endif
