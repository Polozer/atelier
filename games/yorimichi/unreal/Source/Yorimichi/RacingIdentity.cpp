#include "RacingIdentity.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"

bool RacingIdentity::IsValidInstallId(const FString& Id)
{
    if (Id.Len() != InstallIdChars) return false;
    for (const TCHAR C : Id)
        if (!FChar::IsHexDigit(C)) return false;
    return true;
}

FString RacingIdentity::NewInstallId()
{
    return FGuid::NewGuid().ToString(EGuidFormats::Digits);
}

FString RacingIdentity::ParseFile(const FString& Text)
{
    FString Id = Text.TrimStartAndEnd();
    if (Id.StartsWith(HostPrefix)) Id.RightChopInline(FCString::Strlen(HostPrefix));
    return IsValidInstallId(Id) ? Id : FString();
}

FString RacingIdentity::LoadOrCreate(const FString& Path, bool* bSaved)
{
    FString Text;
    if (FFileHelper::LoadFileToString(Text, *Path))
    {
        const FString Id = ParseFile(Text);
        if (!Id.IsEmpty())
        {
            if (bSaved) *bSaved = true;
            return Id;
        }
        UE_LOG(LogTemp, Warning, TEXT("RACING identity: %s holds no valid id, a new one replaces it"), *Path);
    }
    const FString Id = NewInstallId();
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), true);
    // The same text as before guests had an identity ("local:<id>"), so an existing host keeps its player.
    const bool bOk = FFileHelper::SaveStringToFile(HostKey(Id), *Path);
    if (!bOk) UE_LOG(LogTemp, Warning, TEXT("RACING identity: cannot write %s, this id lasts for this run only"), *Path);
    if (bSaved) *bSaved = bOk;
    return Id;
}

FString RacingIdentity::ResolveGuest(const FString& Presented, const FString& SessionPlayerId, const TSet<FString>& Held, FString* Why)
{
    FString Reason;
    FString Key;
    if (!IsValidInstallId(Presented)) Reason = TEXT("no valid install id");
    else
    {
        Key = GuestKey(Presented);
        if (Held.Contains(Key)) Reason = TEXT("its install id is already in this session");
    }
    if (Why) *Why = Reason;
    if (Reason.IsEmpty()) return Key;
    return SessionKey(SessionPlayerId.IsEmpty() ? NewInstallId() : SessionPlayerId);
}
