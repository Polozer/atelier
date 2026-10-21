#include "RacingPlaces.h"
#include "AtelierData.h"
#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

TSharedPtr<FJsonObject> RacingPlaces::Parse(const FString& RuntimeJson, FString* OutError)
{
    TSharedPtr<FJsonObject> Root;
    const TSharedPtr<FJsonObject>* Places = nullptr;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(RuntimeJson), Root) || !Root)
    {
        if (OutError) *OutError = TEXT("invalid JSON");
        return nullptr;
    }
    if (!Root->TryGetObjectField(TEXT("racing_places"), Places) || !Places || !Places->IsValid())
    {
        if (OutError) *OutError = TEXT("no racing_places");
        return nullptr;
    }
    return *Places;
}

TSharedPtr<FJsonObject> RacingPlaces::Belmonte()
{
    static TSharedPtr<FJsonObject> Loaded;
    static bool bTried = false;
    if (!bTried)
    {
        bTried = true;
        const FString Path = AtelierDataPath(TEXT("belmonte/runtime.json"));
        FString Json, Error;
        if (!FFileHelper::LoadFileToString(Json, *Path)) Error = TEXT("cannot read the file");
        else Loaded = Parse(Json, &Error);
        if (!Loaded)
            UE_LOG(LogTemp, Warning, TEXT("RACING places unavailable in %s: %s (run world.belmonte + data.stage)"), *Path, *Error);
    }
    return Loaded;
}

bool RacingPlaces::Vector(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, FVector& Out)
{
    const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
    if (!Object || !Object->TryGetArrayField(Key, A) || !A || A->Num() != 3) return false;
    double V[3];
    for (int32 I = 0; I < 3; ++I)
        if (!(*A)[I].IsValid() || !(*A)[I]->TryGetNumber(V[I]) || !FMath::IsFinite(V[I])) return false;
    Out = FVector(V[0], V[1], V[2]);
    return true;
}

bool RacingPlaces::Number(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double& Out)
{
    return Object && Object->TryGetNumberField(Key, Out) && FMath::IsFinite(Out);
}
