#include "JapanAtlasNames.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/ScopeExit.h"
#include "HAL/FileManager.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FJapanAtlasNamesTest,"Yorimichi.Map.StableNames",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FJapanAtlasNamesTest::RunTest(const FString&)
{
    const FString Dir=FPaths::ProjectSavedDir()/TEXT("Automation/Atlas")/FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString File=Dir/TEXT("names.json");
    ON_SCOPE_EXIT { IFileManager::Get().DeleteDirectory(*Dir,false,true); };
    FJapanAtlasNames Store;Store.Load(File);
    TestEqual(TEXT("An untouched stable uses its English default"),Store.Get(TEXT("alder_stables"),TEXT("Alder Stables")),FString(TEXT("Alder Stables")));
    TestTrue(TEXT("A stable can be renamed"),Store.Rename(TEXT("alder_stables"),TEXT("Willow Run")));
    TestTrue(TEXT("A second stable keeps its independent name"),Store.Rename(TEXT("home_stables"),TEXT("Riverside")));
    TestFalse(TEXT("Blank names cannot erase a label"),Store.Rename(TEXT("alder_stables"),TEXT("   ")));
    TestFalse(TEXT("Control characters cannot enter the atlas"),Store.Rename(TEXT("alder_stables"),TEXT("Bad\nName")));
    TestFalse(TEXT("Stable identities cannot become paths"),Store.Rename(TEXT("../names"),TEXT("Oops")));
    FJapanAtlasNames Reloaded;Reloaded.Load(File);
    TestEqual(TEXT("Stable names persist on a fresh load"),Reloaded.Get(TEXT("alder_stables"),TEXT("Alder Stables")),FString(TEXT("Willow Run")));
    TestEqual(TEXT("Renaming another stable does not replace the first"),Reloaded.Get(TEXT("home_stables"),TEXT("Home Stables")),FString(TEXT("Riverside")));
    TestTrue(TEXT("Reset removes just the selected override"),Reloaded.Reset(TEXT("alder_stables")));
    FJapanAtlasNames Reset;Reset.Load(File);
    TestEqual(TEXT("Reset restores the English default"),Reset.Get(TEXT("alder_stables"),TEXT("Alder Stables")),FString(TEXT("Alder Stables")));
    TestEqual(TEXT("Reset preserves other names"),Reset.Get(TEXT("home_stables"),TEXT("Home Stables")),FString(TEXT("Riverside")));
    const FString Corrupt=Dir/TEXT("corrupt.json");FFileHelper::SaveStringToFile(TEXT("{broken"),*Corrupt);
    FJapanAtlasNames Protected;Protected.Load(Corrupt);
    TestFalse(TEXT("An unreadable prior save cannot be overwritten"),Protected.Rename(TEXT("home_stables"),TEXT("Replacement")));
    FString Original;FFileHelper::LoadFileToString(Original,*Corrupt);
    TestEqual(TEXT("The unreadable save remains byte-for-byte intact"),Original,FString(TEXT("{broken")));
    const FString Blocker=Dir/TEXT("not-a-directory");FFileHelper::SaveStringToFile(TEXT("keep"),*Blocker);
    FJapanAtlasNames Unwritable;Unwritable.Load(Blocker/TEXT("names.json"));
    TestFalse(TEXT("A failed save reports failure"),Unwritable.Rename(TEXT("home_stables"),TEXT("Unavailable")));
    TestEqual(TEXT("A failed save does not publish an in-memory rename"),Unwritable.Get(TEXT("home_stables"),TEXT("Home Stables")),FString(TEXT("Home Stables")));
    return true;
}
#endif
