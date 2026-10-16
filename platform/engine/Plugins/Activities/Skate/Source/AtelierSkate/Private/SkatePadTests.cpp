// SkatePad.h's transfer: Shift, the left bumper (L1), or the left stick pushed forward; the stick steering sideways
// or pulled back (the powerslide) is not one. Both triggers stay pump and grab.
#include "SkatePad.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkatePadTransferTest, "AtelierSkate.Pad.Transfer",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FSkatePadTransferTest::RunTest(const FString&)
{
    using atelier::skate_pad::Transfers;
    TestFalse(TEXT("Nothing held, no transfer"), Transfers(false, 0., 0., false));
    TestTrue(TEXT("Shift"), Transfers(true, 0., 0., false));
    TestTrue(TEXT("The left bumper"), Transfers(false, 0., 0., true));
    TestTrue(TEXT("The stick pushed forward"), Transfers(false, 0., 1., false));
    TestTrue(TEXT("Forward and a little sideways"), Transfers(false, .4, .85, false));
    TestFalse(TEXT("Half forward is still steering"), Transfers(false, 0., .5, false));
    TestFalse(TEXT("More sideways than forward is steering"), Transfers(false, .9, .75, false));
    TestFalse(TEXT("Pulled back is the powerslide"), Transfers(false, 0., -1., false));
    return true;
}
#endif
