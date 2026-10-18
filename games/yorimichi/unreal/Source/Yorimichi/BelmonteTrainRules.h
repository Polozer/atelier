#pragma once
#include "CoreMinimal.h"

/**
 * The Belmonte train's passenger rules, kept pure so automation tests cover them (BelmonteTrainServiceTests.cpp).
 * The train is on foot only: the one way in is the boarding walk (Interact "Monter" at a station door).
 */
namespace BelmonteTrainRules
{
/** The HUD line when a vehicle is refused on the train. */
inline const TCHAR* Refusal() { return TEXT("Pas à bord du train"); }

/** Taking out the skateboard, the bike, the horse or the sailboat: never aboard, seated or while stepping through a
 *  door (bTrainAction). Putting one away is always allowed. */
inline bool MayTakeOutVehicle(bool bAboard, bool bTrainAction) { return !bAboard && !bTrainAction; }

/** A player found inside a coach without having boarded through a door (on a vehicle through an open door, a jump, the
 *  paraglider, a dash) is put back outside; a passenger, a seated player or one stepping through a door is not. */
inline bool MustEject(bool bInsideCoach, bool bAdmitted, bool bBoarding, bool bSeated)
{
    return bInsideCoach && !bAdmitted && !bBoarding && !bSeated;
}
}

/**
 * The camera aboard: third person, or first person once toggled. The choice is remembered (bPreferFirstPerson) for the
 * next boarding; anything that ends "aboard" (Descendre, a teleport, a respawn) returns to third person.
 */
struct FBelmonteTrainView
{
    bool bPreferFirstPerson = false;

    /** Each frame, with whether the player is aboard (standing or seated, not stepping through a door). Returns whether
     *  the first-person view is on. */
    bool Update(bool bAboard)
    {
        if (!bAboard) bFirstPerson = false;
        else if (!bWasAboard) bFirstPerson = bPreferFirstPerson;
        bWasAboard = bAboard;
        return bFirstPerson;
    }
    /** The toggle button: only aboard; returns false (ignored) elsewhere. */
    bool Toggle(bool bAboard)
    {
        if (!bAboard) return false;
        bWasAboard = true;
        bFirstPerson = !bFirstPerson;
        bPreferFirstPerson = bFirstPerson;
        return true;
    }
    bool IsFirstPerson() const { return bFirstPerson; }

private:
    bool bFirstPerson = false, bWasAboard = false;
};
