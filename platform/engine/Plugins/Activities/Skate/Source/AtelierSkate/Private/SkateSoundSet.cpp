#include "SkateSoundSet.h"
#include "SkateComponent.h"
#include "Components/AudioComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "AudioDevice.h"
#include "GameFramework/Actor.h"
#include "Sound/SoundWave.h"

FSkateAudioReady USkateComponent::AudioReady;

namespace
{
void SkateApplyLowPass(UAudioComponent* Voice, bool bSoften)
{
    // Play copies these properties; the setters reach only an already-active sound.
    Voice->LowPassFilterFrequency = 3000.f;
    Voice->bEnableLowPassFilter = bSoften;
    Voice->SetLowPassFilterFrequency(3000.f);
    Voice->SetLowPassFilterEnabled(bSoften);
}
}

bool USkateComponent::CanSetSoundSet(const USkateSoundSet* Replacement, FString& Error) const
{
    Error.Reset();
    if (!IsInGameThread()) { Error = TEXT("Sound selection requires the game thread."); return false; }
    // A fresh/default selection never changes legacy references, random state or envelopes.
    if (!Replacement && !bOriginalSoundsCaptured) return true;
    if (GetWorld() && GetWorld()->GetNetMode() == NM_DedicatedServer)
    { Error = TEXT("Sound selection is client presentation."); return false; }
    TArray<FName> LoopKeys = {TEXT("roll"), TEXT("grind"), TEXT("slide"), TEXT("skid"), TEXT("scrape")};
    TSet<FName> CueKeys = {TEXT("pop"), TEXT("land"), TEXT("catch"), TEXT("push"), TEXT("flick"), TEXT("clatter"), TEXT("fall")};
    for (const TCHAR* SurfaceName : SurfaceRolls)
    {
        LoopKeys.Add(FName(*FString::Printf(TEXT("roll_%s"), SurfaceName)));
        CueKeys.Add(FName(*FString::Printf(TEXT("land_%s"), SurfaceName)));
        CueKeys.Add(FName(*FString::Printf(TEXT("pop_%s"), SurfaceName)));
    }
    if (Loops.Num() != LoopKeys.Num() || LoopVolume.Num() != Loops.Num())
    { Error = TEXT("Skate audio has not initialized."); return false; }
    for (const auto& Loop : Loops)
        if (!IsValid(Loop)) { Error = TEXT("A skate audio component is unavailable."); return false; }
    if (Replacement)
    {
        if (!IsValid(Replacement) || Replacement->OneShots.Num() + Replacement->Loops.Num() == 0)
        { Error = TEXT("The sound set is empty or unavailable."); return false; }
        for (const auto& Pair : Replacement->OneShots)
        {
            if (!CueKeys.Contains(Pair.Key) || Pair.Value.Variants.IsEmpty() || Pair.Value.Variants.Num() > 12)
            { Error = TEXT("Unknown cue or invalid variant count."); return false; }
            for (const auto& Wave : Pair.Value.Variants)
                if (!IsValid(Wave) || Wave->bLooping || !FMath::IsFinite(Wave->Duration) || Wave->Duration <= 0.f)
                { Error = TEXT("One-shot variants must be loaded finite nonlooping waves."); return false; }
        }
        for (const auto& Pair : Replacement->Loops)
            if (!LoopKeys.Contains(Pair.Key) || !IsValid(Pair.Value) || !Pair.Value->bLooping
                    || !FMath::IsFinite(Pair.Value->Duration) || Pair.Value->Duration <= 0.f)
            { Error = TEXT("Unknown loop or invalid looping wave."); return false; }
    }
    return true;
}

bool USkateComponent::SetSoundSet(USkateSoundSet* Replacement, FString& Error)
{
    if (!CanSetSoundSet(Replacement, Error)) return false;
    if (!Replacement && !bOriginalSoundsCaptured) return true;
    TArray<FName> LoopKeys = {TEXT("roll"), TEXT("grind"), TEXT("slide"), TEXT("skid"), TEXT("scrape")};
    for (const TCHAR* SurfaceName : SurfaceRolls)
        LoopKeys.Add(FName(*FString::Printf(TEXT("roll_%s"), SurfaceName)));
    // Build a complete next state from Original, never from a partially overridden current set.
    TArray<TObjectPtr<USoundWave>> NextWaves = bOriginalSoundsCaptured ? OriginalWaves : Waves;
    TMap<FName, FIntPoint> NextRanges = bOriginalSoundsCaptured ? OriginalCueRange : CueRange;
    TArray<TObjectPtr<USoundWave>> NextLoops = OriginalLoops;
    if (!bOriginalSoundsCaptured)
        for (const auto& Loop : Loops) NextLoops.Add(Cast<USoundWave>(Loop->Sound));
    if (Replacement)
    {
        // Stable ordering keeps variant bookkeeping independent of TMap insertion order.
        TArray<FName> Ordered;
        Replacement->OneShots.GetKeys(Ordered);
        Ordered.Sort(FNameLexicalLess());
        for (FName Key : Ordered)
        {
            const auto& Variants = Replacement->OneShots[Key].Variants;
            const int32 First = NextWaves.Num();
            NextWaves.Append(Variants);
            NextRanges.Add(Key, FIntPoint(First, Variants.Num()));
        }
        for (int32 I = 0; I < LoopKeys.Num(); ++I)
            if (const auto* Wave = Replacement->Loops.Find(LoopKeys[I])) NextLoops[I] = *Wave;
    }
    if (!bOriginalSoundsCaptured)
    {
        OriginalWaves = Waves;
        OriginalCueRange = CueRange;
        for (const auto& Loop : Loops) OriginalLoops.Add(Cast<USoundWave>(Loop->Sound));
        bOriginalSoundsCaptured = true;
    }
    // No asynchronous work occurs between validation and this game-thread commit.
    for (int32 I = 0; I < Loops.Num(); ++I)
        if (Loops[I]->Sound.Get() != NextLoops[I].Get())
        {
            Loops[I]->Stop();
            Loops[I]->SetVolumeMultiplier(0.f);
            LoopVolume[I] = 0.f;
            Loops[I]->SetSound(NextLoops[I].Get());
        }
    Waves = MoveTemp(NextWaves);
    CueRange = MoveTemp(NextRanges);
    LastVariant = -1;
    ActiveSoundSet = Replacement;
    return true;
}

void USkateComponent::ApplyVoicePreferences(UAudioComponent* Voice, float BaseVolume) const
{
    Voice->SetVolumeMultiplier(BaseVolume * SoundVolume);
    SkateApplyLowPass(Voice, bSoftenSounds);
}

void USkateComponent::SetAudioPreferences(bool bSoften, float Volume)
{
    if (!IsInGameThread() || !FMath::IsFinite(Volume)) return;
    const float Clamped = FMath::Clamp(Volume, 0.f, 1.f);
    // Default and repeated requests leave legacy loop components and envelopes untouched.
    if (bSoften == bSoftenSounds && Clamped == SoundVolume) return;
    bSoftenSounds = bSoften;
    SoundVolume = Clamped;
    for (int32 I = 0; I < Loops.Num(); ++I)
        if (UAudioComponent* Loop = Loops[I])
        {
            SkateApplyLowPass(Loop, bSoftenSounds);
            // The same audible threshold as UpdateAudio; silent loops receive the gain when they next sound.
            if (LoopVolume.IsValidIndex(I) && LoopVolume[I] > .01f) Loop->SetVolumeMultiplier(LoopVolume[I] * SoundVolume);
        }
    for (auto It = ShotVoices.CreateIterator(); It; ++It)
        if (UAudioComponent* Voice = It.Key().Get()) ApplyVoicePreferences(Voice, It.Value());
        else It.RemoveCurrent();
}

void USkateComponent::PlayShotVoice(USoundWave* Wave, const FVector& At, float Volume, float Pitch)
{
    UWorld* World = GetWorld();
    if (!Wave || !World || !World->bAllowAudioPlayback || World->IsNetMode(NM_DedicatedServer)
        || !GEngine || !GEngine->UseSound()) return;
    for (auto It = ShotVoices.CreateIterator(); It; ++It)
        if (!It.Key().IsValid()) It.RemoveCurrent();
    // The same spatial component factory as SpawnSoundAtLocation, configured
    // before Play so even the first attack receives the requested filter.
    FAudioDevice::FCreateComponentParams Params(World, GetOwner());
    Params.SetLocation(At);
    Params.AttenuationSettings = Attenuation;
    Params.bPlay = false;
    if (UAudioComponent* Voice = FAudioDevice::CreateComponent(Wave, Params))
    {
        Voice->SetWorldLocationAndRotation(At, FRotator::ZeroRotator);
        Voice->SetPitchMultiplier(Pitch);
        Voice->bAllowSpatialization = Params.ShouldUseAttenuation();
        Voice->bIsUISound = !World->IsGameWorld();
        Voice->bAutoDestroy = true;
        Voice->bStopWhenOwnerDestroyed = true;
        Voice->SubtitlePriority = Wave->GetSubtitlePriority();
        ApplyVoicePreferences(Voice, Volume);
        ShotVoices.Add(Voice, Volume);
        Voice->Play(0.f);
    }
}

void USkateComponent::StopShotVoices()
{
    const auto Voices = MoveTemp(ShotVoices);
    ShotVoices.Reset();
    for (const auto& Pair : Voices)
        if (UAudioComponent* Voice = Pair.Key.Get())
        {
            Voice->Stop();
            if (IsValid(Voice)) Voice->DestroyComponent();
        }
}
