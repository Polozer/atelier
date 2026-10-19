#include "JapanFootsteps.h"
#include "JapanSoundBank.h"
#include "Engine/World.h"
#include "Sound/SoundWave.h"

bool UJapanFootstepComponent::CanSetSoundBank(const UJapanSoundBank* Replacement, FString& Error) const
{
    Error.Reset();
    if(!IsInGameThread()) { Error=TEXT("Sound selection requires the game thread."); return false; }
    if(!Replacement) return true;
    if(!IsValid(Set) || !IsValid(Replacement))
    { Error=TEXT("Footstep audio is not ready."); return false; }
    if(GetWorld() && GetWorld()->GetNetMode()==NM_DedicatedServer)
    { Error=TEXT("Sound selection is client presentation."); return false; }
    TSet<FName> Required={TEXT("barefoot"),TEXT("dirt_gravel"),TEXT("grass"),TEXT("leaves"),TEXT("mud_water"),TEXT("stone"),TEXT("wood")};
    if(Replacement->Footsteps.Num()!=Required.Num() || !Required.Contains(Set->DefaultSurface)
            || (!Set->CanopySurface.IsNone() && !Required.Contains(Set->CanopySurface)))
    { Error=TEXT("Incomplete footstep surface coverage."); return false; }
    for(const auto& Pair:Set->MaterialSurfaces)
        if(!Required.Contains(Pair.Value)) { Error=TEXT("A mapped material lacks alternative coverage."); return false; }
    for(const auto& Pair:Replacement->Footsteps)
    {
        if(!Required.Contains(Pair.Key) || Pair.Value.Variants.Num()<4 || Pair.Value.Variants.Num()>12)
        { Error=TEXT("Invalid footstep surface or variant count."); return false; }
        for(const auto& Wave:Pair.Value.Variants)
            if(!IsValid(Wave) || Wave->bLooping || !FMath::IsFinite(Wave->Duration)
                    || Wave->Duration<.07f || Wave->Duration>1.2f)
            { Error=TEXT("Invalid footstep contact wave."); return false; }
    }
    return true;
}

bool UJapanFootstepComponent::SetSoundBank(UJapanSoundBank* Replacement, FString& Error)
{
    if(!CanSetSoundBank(Replacement,Error)) return false;
    if(SoundBank.Get()==Replacement) return true;
    SoundBank=Replacement;
    AlternativeBags.Reset();
    // Set, its attenuation/material mapping, Original bags and all plant/movement state stay intact.
    return true;
}
