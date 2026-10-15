// SkatePad.h's right trigger: the transfer from the board and on into the air it was held into, a grab once let go and
// pulled again in the air, and the transfer again once the board is down.
#include "SkatePad.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkatePadRightTriggerTest, "AtelierSkate.Pad.RightTrigger",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FSkatePadRightTriggerTest::RunTest(const FString&)
{
    using atelier::skate_pad::RightTriggerTransfers;
    bool bGrabs = false;
    TestFalse(TEXT("Let go on the board, it is nothing"), RightTriggerTransfers(false, false, bGrabs));
    TestTrue(TEXT("Pulled rolling up the ramp, it is the transfer"), RightTriggerTransfers(true, false, bGrabs));
    TestTrue(TEXT("Held on over the lip, it stays the transfer"), RightTriggerTransfers(true, true, bGrabs));
    TestFalse(TEXT("Let go in the air, it is nothing"), RightTriggerTransfers(false, true, bGrabs));
    TestFalse(TEXT("Pulled again in the air, it grabs"), RightTriggerTransfers(true, true, bGrabs));
    TestFalse(TEXT("Held as the grab, it is still not the transfer"), RightTriggerTransfers(true, true, bGrabs));
    TestTrue(TEXT("Still held when the board is down, it is the transfer again"), RightTriggerTransfers(true, false, bGrabs));
    bGrabs = false;
    TestFalse(TEXT("An air launched without it: the first air frame lets it grab"), RightTriggerTransfers(false, true, bGrabs));
    TestFalse(TEXT("Pulled in that air, it grabs"), RightTriggerTransfers(true, true, bGrabs));
    return true;
}
#endif
