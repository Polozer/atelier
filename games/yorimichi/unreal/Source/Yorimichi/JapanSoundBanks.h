#pragma once
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "Containers/Ticker.h"
#include "JapanSoundBanks.generated.h"

class UJapanSoundBank;
class UJapanFootstepComponent;
class USkateComponent;
class UAudioComponent;
class USoundWave;
struct FStreamableHandle;

struct FJapanSoundChoice
{
    FString Id, Label, Asset, Audition, Manifest;
    int32 Selection = 0;
};

/** This client's presentation choice for its local world, including remote emitters.
 * No simulation state, replicated preference or server travel authority belongs here. */
UCLASS()
class YORIMICHI_API UJapanSoundBanks : public UWorldSubsystem
{
    GENERATED_BODY()
public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    void Restore(int32 Selection);
    void Cycle(int32 Direction, TFunction<bool(int32)> Persist);
    void Select(int32 Selection, TFunction<bool(int32)> Persist = {});
    void Preview();
    void StopPreview();
    bool IsPreviewing() const { return Audition != nullptr || PreviewLoading.IsValid(); }
    FString Label();
    const FString& Error() const { return LastError; }
    int32 Selection() const { return ActiveSelection; }
protected:
    virtual bool DoesSupportWorldType(EWorldType::Type Type) const override
    { return Type == EWorldType::Game || Type == EWorldType::PIE; }
private:
    friend class FJapanSoundBankSelectionTest;
    friend class FJapanSoundBankCompletionTest;
    bool ReadRegistry();
    bool RegistryCurrent(FString& Error) const;
    bool MatchesRegistry(const FString& Current) const;
    bool Validate(const FJapanSoundChoice& Choice, UJapanSoundBank* Bank, FString& Error) const;
    bool Commit(const FJapanSoundChoice& Choice, UJapanSoundBank* Bank, const TFunction<bool(int32)>& Persist);
    void FootReady(UJapanFootstepComponent* Component);
    void SkateReady(USkateComponent* Component);
    void CancelSelection();
    void ArmTimeout(bool Preview,uint64 Token);
    void PreviewLoaded(uint64 Token,const FJapanSoundChoice& Choice);
    TArray<FJapanSoundChoice> Choices;
    bool bRegistryLoaded = false, bRegistryAttempted = false, bRestored = false, bShuttingDown = false;
    uint64 Generation = 0, PreviewGeneration = 0;
    int32 ActiveSelection = 0, RequestedSelection = 0;
    FString LastError;
    FString RegistrySnapshot;
    TSharedPtr<FStreamableHandle> Loading, PreviewLoading;
    FDelegateHandle FootHandle, SkateHandle, BackgroundHandle, DeactivateHandle;
    FTSTicker::FDelegateHandle SelectionTimeout, PreviewTimeout;
    UPROPERTY() TObjectPtr<UJapanSoundBank> Active;
    UPROPERTY() TObjectPtr<UAudioComponent> Audition;
    UPROPERTY() TObjectPtr<USoundWave> PreviewWave;
};
