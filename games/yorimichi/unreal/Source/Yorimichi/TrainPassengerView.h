#pragma once
#include "CoreMinimal.h"
#include "Camera/CameraTypes.h"
#include "PrimitiveComponentId.h"

class AWandererCharacter;

/** Local train camera state. Preference belongs to the local controller, independently of pawn replacement. */
struct YORIMICHI_API FTrainPassengerView
{
    bool Toggle(bool bPassenger, bool& bPreference);
    void Update(bool bPassenger, bool bPreference, float DeltaSeconds);
    void Apply(const AWandererCharacter& Rider, float DeltaSeconds, FMinimalViewInfo& View);
    bool IsFirstPerson() const { return bFirstPerson; }
    bool HidesBody() const { return Blend > .5f; }
    /** Adds only to this view's hidden set; never edits component visibility or ownership. */
    static void AddHiddenBodyComponents(const AWandererCharacter& Rider, TSet<FPrimitiveComponentId>& Hidden);
private:
    bool bFirstPerson = false, bWasPassenger = false;
    float Blend = 0.f;
    FVector Eye = FVector::ZeroVector;
};
