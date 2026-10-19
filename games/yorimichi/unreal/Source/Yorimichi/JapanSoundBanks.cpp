#include "JapanSoundBanks.h"
#include "JapanSoundBank.h"
#include "JapanFootsteps.h"
#include "SkateComponent.h"
#include "SkateSoundSet.h"
#include "AtelierData.h"
#include "Components/AudioComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/AssetManager.h"
#include "Engine/Engine.h"
#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/CoreDelegates.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Sound/SoundWave.h"
#include "UObject/UObjectIterator.h"

namespace
{
bool Hash(const FString& Text)
{
    if(Text.Len()!=64) return false;
    for(TCHAR C:Text) if(!((C>=TEXT('0') && C<=TEXT('9')) || (C>=TEXT('a') && C<=TEXT('f')))) return false;
    return true;
}
FString Path(const FString& Id,const TCHAR* Name)
{ return FString::Printf(TEXT("/Game/AudioBanks/%s/%s.%s"),*Id,Name,Name); }
bool Wave(const USoundWave* Value,bool Loop,float Minimum,float Maximum)
{
    return IsValid(Value) && !Value->HasAnyFlags(RF_NeedLoad|RF_NeedPostLoad)
        && Value->NumChannels==1 && Value->GetLoadingBehavior()==ESoundWaveLoadingBehavior::ForceInline
        && Value->GetSoundAssetCompressionType()==ESoundAssetCompressionType::PCM
        && bool(Value->bLooping)==Loop && FMath::IsFinite(Value->Duration)
        && Value->Duration>=Minimum && Value->Duration<=Maximum;
}
template<class T> TArray<T*> Ready(UWorld* World)
{
    TArray<T*> Result;
    for(TObjectIterator<T> It;It;++It)
        if(IsValid(*It) && !It->IsTemplate() && It->GetWorld()==World && It->IsAudioReady()) Result.Add(*It);
    return Result;
}
}

void UJapanSoundBanks::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    if(GetWorld()->GetNetMode()==NM_DedicatedServer) return;
    FootHandle=UJapanFootstepComponent::AudioReady.AddUObject(this,&ThisClass::FootReady);
    SkateHandle=USkateComponent::AudioReady.AddUObject(this,&ThisClass::SkateReady);
    BackgroundHandle=FCoreDelegates::ApplicationWillEnterBackgroundDelegate.AddUObject(this,&ThisClass::StopPreview);
    DeactivateHandle=FCoreDelegates::ApplicationWillDeactivateDelegate.AddUObject(this,&ThisClass::StopPreview);
}
void UJapanSoundBanks::Deinitialize()
{
    bShuttingDown=true;
    CancelSelection(); StopPreview();
    UJapanFootstepComponent::AudioReady.Remove(FootHandle);
    USkateComponent::AudioReady.Remove(SkateHandle);
    FCoreDelegates::ApplicationWillEnterBackgroundDelegate.Remove(BackgroundHandle);
    FCoreDelegates::ApplicationWillDeactivateDelegate.Remove(DeactivateHandle);
    Active=nullptr; Choices.Reset();
    Super::Deinitialize();
}
bool UJapanSoundBanks::ReadRegistry()
{
    if(bRegistryLoaded) return true;
    if(bRegistryAttempted) return false;
    bRegistryAttempted=true;
    const FString File=AtelierDataPath(TEXT("Soundbanks/registry.json"));
    const int64 Size=IFileManager::Get().FileSize(*File);
    FString Text;
    TSharedPtr<FJsonObject> Root;
    if(Size<=0 || Size>1024*1024 || !FFileHelper::LoadFileToString(Text,*File)
        || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Root) || !Root.IsValid())
    { LastError=TEXT("The soundbank registry is missing or invalid. Original remains available."); return false; }
    double Version=0; FString Default,Catalog;
    const TArray<TSharedPtr<FJsonValue>>* Rows=nullptr;
    if(!Root->TryGetNumberField(TEXT("version"),Version) || Version!=1
        || !Root->TryGetStringField(TEXT("default"),Default) || Default!=TEXT("original")
        || !Root->TryGetStringField(TEXT("catalog_sha256"),Catalog) || !Hash(Catalog)
        || !Root->TryGetArrayField(TEXT("banks"),Rows) || Rows->Num()<1 || Rows->Num()>4)
    { LastError=TEXT("The soundbank registry has an unsupported format."); return false; }
    const TArray<FString> Ids={TEXT("original"),TEXT("soft_contact"),TEXT("dry_street"),TEXT("warm_motion")};
    const TArray<FString> Labels={TEXT("Original"),TEXT("Soft Contact"),TEXT("Dry Street"),TEXT("Warm Motion")};
    TSet<int32> Used; TArray<FJapanSoundChoice> Next;
    for(const auto& Value:*Rows)
    {
        const auto Row=Value->AsObject(); FJapanSoundChoice Choice;
        double Selection=-1; bool Legacy=false; FString AuditionHash;
        if(!Row.IsValid() || !Row->TryGetStringField(TEXT("id"),Choice.Id)
            || !Row->TryGetStringField(TEXT("name"),Choice.Label)
            || !Row->TryGetNumberField(TEXT("selection"),Selection)
            || !FMath::IsFinite(Selection) || Selection<0 || Selection>3 || Selection!=FMath::FloorToDouble(Selection)
            || !Row->TryGetBoolField(TEXT("legacy"),Legacy)
            || !Row->TryGetStringField(TEXT("asset"),Choice.Asset)
            || !Row->TryGetStringField(TEXT("audition"),Choice.Audition)
            || !Row->TryGetStringField(TEXT("source_manifest_sha256"),Choice.Manifest)
            || !Row->TryGetStringField(TEXT("audition_sha256"),AuditionHash))
        { LastError=TEXT("A soundbank registry entry is malformed."); return false; }
        Choice.Selection=int32(Selection);
        if(Used.Contains(Choice.Selection) || Choice.Id!=Ids[Choice.Selection] || Choice.Label!=Labels[Choice.Selection]
            || Legacy!=(Choice.Selection==0) || Choice.Audition!=Path(Choice.Id,TEXT("Audition")) || !Hash(AuditionHash)
            || Choice.Asset!=(Legacy?FString():Path(Choice.Id,TEXT("DA_Bank")))
            || (Legacy?(!Next.IsEmpty() || !Choice.Manifest.IsEmpty()):!Hash(Choice.Manifest)))
        { LastError=TEXT("A soundbank identity or asset path has changed."); return false; }
        Used.Add(Choice.Selection); Next.Add(MoveTemp(Choice));
    }
    if(!Used.Contains(0)) { LastError=TEXT("Original is required in the soundbank registry."); return false; }
    Choices=MoveTemp(Next); RegistrySnapshot=MoveTemp(Text); bRegistryLoaded=true;
    return true;
}
bool UJapanSoundBanks::MatchesRegistry(const FString& Current) const
{
    return bRegistryLoaded && !RegistrySnapshot.IsEmpty() && Current==RegistrySnapshot;
}
bool UJapanSoundBanks::RegistryCurrent(FString& Error) const
{
    const FString File=AtelierDataPath(TEXT("Soundbanks/registry.json"));
    const int64 Size=IFileManager::Get().FileSize(*File);
    FString Current;
    if(Size<=0 || Size>1024*1024 || !FFileHelper::LoadFileToString(Current,*File) || !MatchesRegistry(Current))
    {
        Error=TEXT("The installed soundbank registry changed or is unavailable. Restart before selecting another bank.");
        return false;
    }
    return true;
}
FString UJapanSoundBanks::Label()
{
    ReadRegistry();
    const auto* Choice=Choices.FindByPredicate([this](const auto& C){return C.Selection==ActiveSelection;});
    const FString Current=Choice?Choice->Label:TEXT("Original");
    return Loading.IsValid()?Current+TEXT(" (loading choice...)"):Current;
}
void UJapanSoundBanks::Restore(int32 Saved)
{
    if(bRestored || bShuttingDown || GetWorld()->GetNetMode()==NM_DedicatedServer) return;
    bRestored=true;
    // Fresh Original does not load an audition, alternative or even the registry.
    if(Saved!=0) Select(Saved);
}
void UJapanSoundBanks::CancelSelection()
{
    ++Generation;
    FTSTicker::RemoveTicker(SelectionTimeout); SelectionTimeout.Reset();
    if(Loading) Loading->CancelHandle();
    Loading.Reset();
}
void UJapanSoundBanks::ArmTimeout(bool Preview,uint64 Token)
{
    const double Deadline=FPlatformTime::Seconds()+30.;
    auto& Handle=Preview?PreviewTimeout:SelectionTimeout;
    Handle=FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateWeakLambda(this,[this,Preview,Token,Deadline](float)
    {
        if(bShuttingDown || Token!=(Preview?PreviewGeneration:Generation)) return false;
        if(FPlatformTime::Seconds()<Deadline) return true;
        if(Preview) StopPreview(); else { CancelSelection(); RequestedSelection=ActiveSelection; }
        LastError=Preview?TEXT("The soundbank preview load timed out."):TEXT("The soundbank load timed out; the previous bank is still active.");
        return false;
    }),.25f);
}
void UJapanSoundBanks::Cycle(int32 Direction,TFunction<bool(int32)> Persist)
{
    if(!ReadRegistry() || Choices.Num()<2) return;
    int32 Index=Choices.IndexOfByPredicate([this](const auto& C){return C.Selection==RequestedSelection;});
    if(Index==INDEX_NONE) Index=0;
    Index=(Index+(Direction<0?-1:1)+Choices.Num())%Choices.Num();
    Select(Choices[Index].Selection,MoveTemp(Persist));
}
void UJapanSoundBanks::Select(int32 Selection,TFunction<bool(int32)> Persist)
{
    if(!IsInGameThread() || bShuttingDown || GetWorld()->GetNetMode()==NM_DedicatedServer) return;
    CancelSelection(); StopPreview(); LastError.Reset();
    RequestedSelection=ActiveSelection;
    if(!ReadRegistry()) return;
    const auto* Found=Choices.FindByPredicate([Selection](const auto& C){return C.Selection==Selection;});
    if(!Found) { LastError=TEXT("That soundbank is unavailable in this build."); return; }
    const FJapanSoundChoice Choice=*Found;
    RequestedSelection=Selection;
    if(Selection==0) { Commit(Choice,nullptr,Persist); return; }
    const uint64 Token=Generation;
    Loading=UAssetManager::GetStreamableManager().RequestAsyncLoad(FSoftObjectPath(Choice.Asset),
        FStreamableDelegate::CreateWeakLambda(this,[this,Token,Choice,Persist=MoveTemp(Persist)]
        {
            if(bShuttingDown || Generation!=Token) return;
            FTSTicker::RemoveTicker(SelectionTimeout); SelectionTimeout.Reset();
            auto* Bank=Cast<UJapanSoundBank>(FSoftObjectPath(Choice.Asset).ResolveObject());
            Commit(Choice,Bank,Persist);
            Loading.Reset();
        }));
    if(!Loading) LastError=TEXT("Could not start loading the soundbank.");
    else ArmTimeout(false,Token);
}
bool UJapanSoundBanks::Validate(const FJapanSoundChoice& Choice,UJapanSoundBank* Bank,FString& Error) const
{
    if(Choice.Selection==0) return Bank==nullptr;
    auto Fail=[&Error] { Error=TEXT("The loaded soundbank does not match its complete installed definition."); return false; };
    if(!IsValid(Bank) || Bank->GetPathName()!=Choice.Asset || Bank->Key!=FName(*Choice.Id)
        || Bank->SourceManifestHash!=Choice.Manifest || !Wave(Bank->Audition,false,15.999f,16.001f)
        || Bank->Audition->GetPathName()!=Choice.Audition) return Fail();
    const auto* Skate=Cast<USkateSoundSet>(Bank->Skate);
    if(!IsValid(Skate) || Skate->GetPathName()!=Path(Choice.Id,TEXT("DA_Skate"))) return Fail();
    const TSet<FName> Feet={TEXT("barefoot"),TEXT("dirt_gravel"),TEXT("grass"),TEXT("leaves"),TEXT("mud_water"),TEXT("stone"),TEXT("wood")};
    TSet<USoundWave*> Used;
    auto Accept=[&](USoundWave* Sound,bool Loop)
    {
        if(!Wave(Sound,Loop,Loop?.5f:.07f,Loop?4.f:1.2f) || Used.Contains(Sound)
            || !Sound->GetPathName().StartsWith(TEXT("/Game/AudioBanks/")+Choice.Id+TEXT("/W_"))) return false;
        Used.Add(Sound); return true;
    };
    if(Bank->Footsteps.Num()!=Feet.Num()) return Fail();
    for(const auto& Pair:Bank->Footsteps)
    {
        if(!Feet.Contains(Pair.Key) || Pair.Value.Variants.Num()<4 || Pair.Value.Variants.Num()>12) return Fail();
        for(const auto& Sound:Pair.Value.Variants) if(!Accept(Sound,false)) return Fail();
    }
    const TSet<FName> Shots={TEXT("land"),TEXT("land_wood"),TEXT("land_metal"),TEXT("land_asphalt"),TEXT("land_stone"),TEXT("land_dirt"),TEXT("land_grass"),TEXT("land_sand")};
    const TSet<FName> Loops={TEXT("roll"),TEXT("roll_wood"),TEXT("roll_metal"),TEXT("roll_asphalt"),TEXT("roll_stone"),TEXT("roll_dirt"),TEXT("roll_grass"),TEXT("roll_sand"),TEXT("skid")};
    if(Skate->OneShots.Num()!=Shots.Num() || Skate->Loops.Num()!=Loops.Num()) return Fail();
    for(const auto& Pair:Skate->OneShots)
    {
        if(!Shots.Contains(Pair.Key) || Pair.Value.Variants.Num()<2 || Pair.Value.Variants.Num()>4) return Fail();
        for(const auto& Sound:Pair.Value.Variants) if(!Accept(Sound,false)) return Fail();
    }
    for(const auto& Pair:Skate->Loops) if(!Loops.Contains(Pair.Key) || !Accept(Pair.Value,true)) return Fail();
    return true;
}
bool UJapanSoundBanks::Commit(const FJapanSoundChoice& Choice,UJapanSoundBank* Bank,const TFunction<bool(int32)>& Persist)
{
    if(!IsInGameThread() || bShuttingDown || !GetWorld() || GetWorld()->GetNetMode()==NM_DedicatedServer) return false;
    // The captured choice was admitted against this exact snapshot. A restage,
    // removal or failed read during async loading must refuse before saving or
    // touching emitters; stale cached metadata is never activation authority.
    if(!RegistryCurrent(LastError)) return false;
    if(!Validate(Choice,Bank,LastError)) return false;
    auto Feet=Ready<UJapanFootstepComponent>(GetWorld());
    auto Skates=Ready<USkateComponent>(GetWorld());
    auto* Skate=Bank?Cast<USkateSoundSet>(Bank->Skate):nullptr;
    for(auto* Component:Feet) if(!Component->CanSetSoundBank(Bank,LastError)) return false;
    for(auto* Component:Skates) if(!Component->CanSetSoundSet(Skate,LastError)) return false;
    if(Persist && !Persist(Choice.Selection))
    { LastError=TEXT("The soundbank preference could not be saved; the previous bank is still active."); return false; }
    const bool Changed=Active.Get()!=Bank;
    // No async work, callbacks or collection between this preflight and commit.
    // Set's validation is identical to CanSet and cannot change on this game thread.
    if(Changed)
    {
        for(auto* Component:Feet) { const bool Ok=Component->SetSoundBank(Bank,LastError); check(Ok); }
        for(auto* Component:Skates) { const bool Ok=Component->SetSoundSet(Skate,LastError); check(Ok); }
        // Preview can be started after Select began. Invalidate that old-bank
        // completion/player at the successful commit, before publishing its label.
        StopPreview();
    }
    Active=Bank; ActiveSelection=RequestedSelection=Choice.Selection;
    LastError.Reset();
    if(Changed && GEngine) GEngine->ForceGarbageCollection(false);
    return true;
}
void UJapanSoundBanks::FootReady(UJapanFootstepComponent* Component)
{
    if(!bShuttingDown && Active && IsValid(Component) && Component->GetWorld()==GetWorld())
        if(!RegistryCurrent(LastError) || !Component->SetSoundBank(Active,LastError)) UE_LOG(LogTemp,Error,TEXT("Soundbank new foot emitter: %s"),*LastError);
}
void UJapanSoundBanks::SkateReady(USkateComponent* Component)
{
    if(!bShuttingDown && Active && IsValid(Component) && Component->GetWorld()==GetWorld())
        if(!RegistryCurrent(LastError) || !Component->SetSoundSet(Cast<USkateSoundSet>(Active->Skate),LastError)) UE_LOG(LogTemp,Error,TEXT("Soundbank new skate emitter: %s"),*LastError);
}
void UJapanSoundBanks::StopPreview()
{
    ++PreviewGeneration;
    FTSTicker::RemoveTicker(PreviewTimeout); PreviewTimeout.Reset();
    if(PreviewLoading) PreviewLoading->CancelHandle();
    PreviewLoading.Reset();
    if(UAudioComponent* Previous=Audition)
    {
        Audition=nullptr;
        Previous->OnAudioFinishedNative.RemoveAll(this);
        Previous->Stop(); Previous->DestroyComponent();
    }
    PreviewWave=nullptr;
}
void UJapanSoundBanks::Preview()
{
    if(!IsInGameThread() || bShuttingDown || GetWorld()->GetNetMode()==NM_DedicatedServer) return;
    StopPreview();
    if(bShuttingDown || !ReadRegistry()) return;
    const auto* Found=Choices.FindByPredicate([this](const auto& C){return C.Selection==ActiveSelection;});
    if(!Found) return;
    const FJapanSoundChoice Choice=*Found;
    const uint64 Token=PreviewGeneration;
    PreviewLoading=UAssetManager::GetStreamableManager().RequestAsyncLoad(FSoftObjectPath(Choice.Audition),
        FStreamableDelegate::CreateWeakLambda(this,[this,Token,Choice]
        { PreviewLoaded(Token,Choice); }));
    if(PreviewLoading) ArmTimeout(true,Token);
    else LastError=TEXT("Could not start loading the soundbank preview.");
}
void UJapanSoundBanks::PreviewLoaded(uint64 Token,const FJapanSoundChoice& Choice)
{
    if(bShuttingDown || PreviewGeneration!=Token) return;
    FTSTicker::RemoveTicker(PreviewTimeout); PreviewTimeout.Reset();
    if(!RegistryCurrent(LastError)) { PreviewLoading.Reset(); return; }
    auto* Sound=Cast<USoundWave>(FSoftObjectPath(Choice.Audition).ResolveObject());
    if(!Wave(Sound,false,15.999f,16.001f) || Sound->GetPathName()!=Choice.Audition)
    { LastError=TEXT("The soundbank preview is unavailable."); PreviewLoading.Reset(); return; }
    PreviewWave=Sound;
    Audition=NewObject<UAudioComponent>(this);
    Audition->bAutoActivate=false; Audition->bAutoDestroy=false;
    Audition->bAllowSpatialization=false; Audition->bIsUISound=true;
    Audition->RegisterComponentWithWorld(GetWorld()); Audition->SetSound(Sound);
    Audition->OnAudioFinishedNative.AddWeakLambda(this,[this,Token](UAudioComponent* Finished)
    { if(PreviewGeneration==Token && Audition==Finished) StopPreview(); });
    Audition->Play(); PreviewLoading.Reset();
}
