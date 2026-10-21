#pragma once
#include "CoreMinimal.h"

class UWorld;
class UJapanGameInstance;

/**
 * The racing stack between a listen host and a guest (-networkqa=server|client -networklisten -networkracing,
 * tools/review_network_racing.py). The guest checks its persistent identity (a kept wallet, the Hidamari stable), a stable
 * request, a records page and win bets settled on a race both machines sample, then leaves for Solo and joins again to
 * find its wallet, tickets and stable back. Both machines sample the race, the train line and their frame rate into
 * racing-<role>.json receipts in the QA folder; the review script compares them. Development diagnostics only: no
 * network control endpoint.
 */
namespace RacingNetworkQA
{
    /** One step; true once this machine's part is done (until then the base lifecycle neither leaves nor finishes).
     *  Fills Error on a failure. */
    bool Tick(UJapanGameInstance* Session, UWorld* World, bool bServer, const FString& Folder, FString& Error);
    /** The guest left on purpose and is joining again: the base lifecycle must not count it as a lost connection. */
    bool IsRejoining();
}
