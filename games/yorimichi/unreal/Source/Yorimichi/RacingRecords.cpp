#include "RacingRecords.h"
#include "RacingPlaces.h"
#include "HRClock.h"
#include "HRContent.h"
#include "HRRules.h"
#include "HRSave.h"
#include "JapanHUD.h"
#include "LiveLibrary.h"
#include "RacingBetting.h"
#include "RacingService.h"
#include "RacingStables.h"
#include "SkateComponent.h"
#include "WandererCharacter.h"
#include "Brushes/SlateRoundedBoxBrush.h"
#include "Components/StaticMeshComponent.h"
#include "Components/TextRenderComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "Input/Events.h"
#include "InputCoreTypes.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Net/UnrealNetwork.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/ConstructorHelpers.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Text/STextBlock.h"

// ------------------------------------------------------------------------------------------------------------ ledger

FString FRacingLedger::ToJson() const
{
    auto E = [](const FString& T) { return RacingJsonEscape(T); };
    FString RecordsJson, RidersJson, SeenJson;
    for (const FRacingRecordTime& R : this->Records)
        RecordsJson += FString::Printf(TEXT("%s{\"key\":\"%s\",\"distance\":%d,\"time_us\":%lld,\"horse_id\":\"%s\",\"horse\":\"%s\",\"rider_id\":\"%s\",\"jockey\":\"%s\","
            "\"stable_id\":\"%s\",\"stable\":\"%s\",\"t\":%d,\"race\":\"%s\"}"), RecordsJson.IsEmpty() ? TEXT("") : TEXT(","), *E(R.Key), R.Distance, R.TimeUs,
            *E(R.HorseId), *E(R.Horse), *E(R.RiderId), *E(R.Jockey), *E(R.StableId), *E(R.Stable), R.T, *E(R.Race));
    TArray<FString> Ids;
    this->Riders.GetKeys(Ids);
    Ids.Sort();
    for (const FString& Id : Ids)
    {
        const FRacingRiderTally& T = this->Riders[Id];
        RidersJson += FString::Printf(TEXT("%s\"%s\":{\"name\":\"%s\",\"rides\":%d,\"wins\":%d,\"gp\":%d,\"earnings\":%d,\"streak\":%d,\"best_streak\":%d}"),
            RidersJson.IsEmpty() ? TEXT("") : TEXT(","), *E(Id), *E(T.Name), T.Rides, T.Wins, T.GpWins, T.Earnings, T.Streak, T.BestStreak);
    }
    TArray<FString> SeenSorted = Seen.Array();
    SeenSorted.Sort();
    for (const FString& S : SeenSorted) SeenJson += FString::Printf(TEXT("%s\"%s\""), SeenJson.IsEmpty() ? TEXT("") : TEXT(","), *E(S));
    return FString::Printf(TEXT("{\"version\":%d,\"seed\":\"%s\",\"since\":%d,\"records\":[%s],\"riders\":{%s},\"seen\":[%s]}"), Version, *E(Seed), SinceT,
        *RecordsJson, *RidersJson, *SeenJson);
}

bool FRacingLedger::FromJson(const FString& Json, FRacingLedger& Out)
{
    // Admission before any change to Out: version, bounded collections and strings, unique keys, sane numbers.
    TSharedPtr<FJsonObject> D;
    if (Json.Len() > HRSave::MaxJsonChars || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), D) || !D) return false;
    int32 V = 0;
    if (!D->TryGetNumberField(TEXT("version"), V) || V != Version) return false;
    constexpr int32 MaxText = 256;
    auto Text = [](const TSharedPtr<FJsonObject>& O, const TCHAR* Key, FString& To, int32 Max, bool bRequired)
    {
        if (!O->HasField(Key)) return !bRequired;
        const TSharedPtr<FJsonValue> Field = O->TryGetField(Key);
        return Field.IsValid() && Field->Type == EJson::String && Field->TryGetString(To) && To.Len() <= Max && (!bRequired || !To.IsEmpty());
    };
    auto Count = [](const TSharedPtr<FJsonObject>& O, const TCHAR* Key, int32& To, int32 Max)
    {
        if (!O->HasField(Key)) return true;
        double N = 0.;
        if (!O->TryGetNumberField(Key, N) || !FMath::IsFinite(N) || N < 0. || N > Max || N != FMath::FloorToDouble(N)) return false;
        To = int32(N);
        return true;
    };
    FRacingLedger L;
    if (!Text(D, TEXT("seed"), L.Seed, MaxText, false)) return false;
    double Since = -1.;
    if (D->HasField(TEXT("since")) && (!D->TryGetNumberField(TEXT("since"), Since) || !FMath::IsFinite(Since) || Since < -1. ||
        Since > HRSave::MaxDay || Since != FMath::FloorToDouble(Since)))
        return false;
    L.SinceT = int32(Since);
    const TArray<TSharedPtr<FJsonValue>>* RecordsArray = nullptr;
    if (D->TryGetArrayField(TEXT("records"), RecordsArray))
    {
        if (RecordsArray->Num() > MaxRecords) return false;
        TSet<FString> Keys;
        for (const TSharedPtr<FJsonValue>& Value : *RecordsArray)
        {
            const TSharedPtr<FJsonObject> O = Value.IsValid() ? Value->AsObject() : nullptr;
            if (!O) return false;
            FRacingRecordTime& R = L.Records.AddDefaulted_GetRef();
            double Time = 0.;
            bool bDuplicate = false;
            if (!Text(O, TEXT("key"), R.Key, HRSave::MaxIdChars, true) || !O->TryGetNumberField(TEXT("time_us"), Time) ||
                !FMath::IsFinite(Time) || Time <= 0. || Time > 1e12) return false;
            Keys.Add(R.Key, &bDuplicate);
            if (bDuplicate) return false;
            R.TimeUs = int64(Time);
            if (!Count(O, TEXT("distance"), R.Distance, 100000) || !Count(O, TEXT("t"), R.T, HRSave::MaxDay) ||
                !Text(O, TEXT("horse_id"), R.HorseId, HRSave::MaxIdChars, false) || !Text(O, TEXT("horse"), R.Horse, MaxText, false) ||
                !Text(O, TEXT("rider_id"), R.RiderId, HRSave::MaxIdChars, false) || !Text(O, TEXT("jockey"), R.Jockey, MaxText, false) ||
                !Text(O, TEXT("stable_id"), R.StableId, HRSave::MaxIdChars, false) || !Text(O, TEXT("stable"), R.Stable, MaxText, false) ||
                !Text(O, TEXT("race"), R.Race, MaxText, false))
                return false;
        }
    }
    const TSharedPtr<FJsonObject>* RidersObject = nullptr;
    if (D->TryGetObjectField(TEXT("riders"), RidersObject))
    {
        if ((*RidersObject)->Values.Num() > HRSave::MaxRiders) return false;
        for (const TPair<FString, TSharedPtr<FJsonValue>>& P : (*RidersObject)->Values)
        {
            const TSharedPtr<FJsonObject> O = P.Value.IsValid() ? P.Value->AsObject() : nullptr;
            if (!O || P.Key.IsEmpty() || P.Key.Len() > HRSave::MaxIdChars) return false;
            FRacingRiderTally& T = L.Riders.Add(P.Key);
            if (!Text(O, TEXT("name"), T.Name, MaxText, false) || !Count(O, TEXT("rides"), T.Rides, MAX_int32) ||
                !Count(O, TEXT("wins"), T.Wins, MAX_int32) || !Count(O, TEXT("gp"), T.GpWins, MAX_int32) ||
                !Count(O, TEXT("earnings"), T.Earnings, MAX_int32) || !Count(O, TEXT("streak"), T.Streak, MAX_int32) ||
                !Count(O, TEXT("best_streak"), T.BestStreak, MAX_int32) || T.Wins > T.Rides || T.Streak > T.Wins || T.BestStreak < T.Streak)
                return false;
        }
    }
    const TArray<TSharedPtr<FJsonValue>>* SeenArray = nullptr;
    if (D->TryGetArrayField(TEXT("seen"), SeenArray))
    {
        if (SeenArray->Num() > MaxSeen) return false;
        for (const TSharedPtr<FJsonValue>& Value : *SeenArray)
        {
            FString Id;
            if (!Value.IsValid() || Value->Type != EJson::String || !Value->TryGetString(Id) || Id.IsEmpty() || Id.Len() > HRSave::MaxIdChars) return false;
            L.Seen.Add(Id);
        }
    }
    Out = MoveTemp(L);
    return true;
}

// ------------------------------------------------------------------------------------------------------------ text

// A named namespace: in a unity build an anonymous one would leak into later files.
namespace RacingRecordsText
{
    /** Upper case, accented Latin-1 letters included. */
    FString Upper(const FString& In)
    {
        FString Out = In.ToUpper();
        for (TCHAR& C : Out.GetCharArray())
            if (C >= 0xE0 && C <= 0xFE && C != 0xF7) C = TCHAR(C - 0x20);
        return Out;
    }

    /** World text draws Latin-1 only: anything else becomes a space. */
    FString Latin1(const FString& In)
    {
        FString Out = In;
        for (TCHAR& C : Out.GetCharArray())
            if (C > 0xFF) C = C == 0x2019 ? TEXT('\'') : C == 0x00B7 ? C : TEXT(' ');
        return Out;
    }

    /** "12 345". */
    FString Number(int64 N)
    {
        FString Digits = FString::Printf(TEXT("%lld"), FMath::Abs(N));
        FString Out;
        for (int32 I = 0; I < Digits.Len(); ++I)
        {
            if (I && (Digits.Len() - I) % 3 == 0) Out.AppendChar(TEXT(' '));
            Out.AppendChar(Digits[I]);
        }
        return N < 0 ? TEXT("-") + Out : Out;
    }

    FString Plural(int32 N, const TCHAR* One, const TCHAR* Many)
    {
        return FString::Printf(TEXT("%s %s"), *Number(N), FMath::Abs(N) > 1 ? Many : One);
    }

    const TCHAR* VenueName(int32 Venue) { return Venue == int32(ERacingVenue::Belmonte) ? TEXT("Belmonte") : TEXT("Hidamari"); }

    FString StableName(const FHRWorldState& S, const FString& Id)
    {
        const FHRStable* St = HRRules::FindStable(S, Id);
        return St ? St->Name : FString();
    }

    /** French round of a career line ("finale", "manche 2"). */
    FString Round(const FString& Round)
    {
        if (Round == TEXT("final")) return TEXT("finale");
        if (Round == TEXT("semi")) return TEXT("manche");
        if (Round == TEXT("qualif")) return TEXT("sprint qualificatif");
        if (Round == TEXT("barrage")) return TEXT("barrage");
        return TEXT("course");
    }

    /** Running order of a race key within its day ("village:1" < "semi:0" < "barrage:0" < "final:0"). */
    int32 Order(const FString& Key)
    {
        FString Round, Group;
        if (!Key.Split(TEXT(":"), &Round, &Group)) Round = Key;
        const int32 Rank = Round == TEXT("final") ? 3 : Round == TEXT("barrage") ? 2 : (Round == TEXT("semi") || Round == TEXT("qualif")) ? 1 : 0;
        return Rank * 1000 + FCString::Atoi(*Group);
    }

    FString Ago(double Seconds)
    {
        if (Seconds <= 0.) return TEXT("en cours");
        const int32 Minutes = FMath::CeilToInt(Seconds / 60.);
        if (Minutes < 60) return FString::Printf(TEXT("dans %d min"), Minutes);
        return FString::Printf(TEXT("dans %d h %02d"), Minutes / 60, Minutes % 60);
    }

    FString Age(int32 Months)
    {
        const int32 Years = FMath::Max(0, Months) / 12, Rest = FMath::Max(0, Months) % 12;
        return Rest ? FString::Printf(TEXT("%d an%s %d mois"), Years, Years > 1 ? TEXT("s") : TEXT(""), Rest) : FString::Printf(TEXT("%d an%s"), Years, Years > 1 ? TEXT("s") : TEXT(""));
    }
}

FString RacingRecords::Time(int64 TimeUs)
{
    const int64 H = HRRules::Hundredths(TimeUs);
    if (H >= 6000) return FString::Printf(TEXT("%lld:%02lld.%02lld"), H / 6000, (H / 100) % 60, H % 100);
    return FString::Printf(TEXT("%lld.%02lld s"), H / 100, H % 100);
}

FString RacingRecords::Date(int32 T)
{
    return FString::Printf(TEXT("saison %d, jour %d"), HRClock::SeasonOf(T) + 1, HRClock::DayOfSeason(T) + 1);
}

const TCHAR* RacingRecords::HonourName(ERacingHonour H)
{
    switch (H)
    {
        case ERacingHonour::Wins: return TEXT("Les plus de victoires");
        case ERacingHonour::Defeats: return TEXT("Les plus de défaites");
        case ERacingHonour::GrandPrix: return TEXT("Les plus de Grands Prix");
        case ERacingHonour::Earnings: return TEXT("Les plus gros gains");
        default: return TEXT("Les plus longues séries");
    }
}

namespace RacingRecordsText
{
    FString Value(ERacingHonour H, int32 V)
    {
        switch (H)
        {
            case ERacingHonour::Wins: return Plural(V, TEXT("victoire"), TEXT("victoires"));
            case ERacingHonour::Defeats: return Plural(V, TEXT("défaite"), TEXT("défaites"));
            case ERacingHonour::GrandPrix: return Plural(V, TEXT("Grand Prix"), TEXT("Grands Prix"));
            case ERacingHonour::Earnings: return Plural(V, TEXT("pièce"), TEXT("pièces"));
            default: return FString::Printf(TEXT("%d de suite"), V);
        }
    }
    /** The short value on a board ("12", "1 234 p."). */
    FString Short(ERacingHonour H, int32 V)
    {
        return H == ERacingHonour::Earnings ? Number(V) + TEXT(" p.") : Number(V);
    }
    const TCHAR* KindName(ERacingHallKind K)
    {
        return K == ERacingHallKind::Horse ? TEXT("Chevaux") : K == ERacingHallKind::Jockey ? TEXT("Jockeys") : TEXT("Écuries");
    }
}

// ------------------------------------------------------------------------------------------------------------ the ledger's notes

int32 RacingRecords::CircuitOf(int32 T)
{
    if (ARacingService::VenueForDay(T) == ERacingVenue::Hidamari) return 0;
    return HRContent::EventForT(T).Surface == 2 ? 2 : 1;
}

const TCHAR* RacingRecords::CircuitName(int32 Circuit)
{
    switch (Circuit)
    {
        case 0: return TEXT("Hippodrome de Hidamari");
        case 1: return TEXT("Belmonte, piste en herbe");
        default: return TEXT("Belmonte, piste en sable");
    }
}

bool RacingRecords::Note(FRacingLedger& L, const FHRWorldState& S, double Now, bool bAll)
{
    bool bChanged = false;
    const int32 Day = S.Meeting.T;
    if (L.SinceT < 0) { L.SinceT = Day; bChanged = true; }
    // Only today's and yesterday's races are remembered as noted: older ones can no longer be in the meeting.
    for (auto It = L.Seen.CreateIterator(); It; ++It)
        if (FCString::Atoi(**It) < Day - 1) { It.RemoveCurrent(); bChanged = true; }
    const HRContent::FEvent* Event = nullptr;
    for (const FHRRace& Race : S.Meeting.Races)
    {
        if (Race.Status != TEXT("run") || Race.Finishes.IsEmpty()) continue;
        const FString Id = FString::Printf(TEXT("%d:%s"), Day, *Race.Key);
        if (L.Seen.Contains(Id)) continue;
        // As the race is seen: once its winner is home.
        if (!bAll)
        {
            const double Start = HRRules::RaceStartSeconds(S, Race.Key);
            if (Start < 0. || Now < Start + Race.Finishes[0].TimeUs / 1e6) continue;
        }
        L.Seen.Add(Id);
        bChanged = true;
        Event = HRContent::FindEvent(Race.EventId);
        const bool bHeat = HRRules::IsHeatRound(Race.Round);
        const FString Name = ARacingService::RaceName(Race);
        // The race's best time (the official winner's; a two-run race keeps each horse's best run).
        const FHRFinish* Best = nullptr;
        for (const FHRFinish& F : Race.Finishes)
            if (F.TimeUs > 0 && (!Best || F.TimeUs < Best->TimeUs)) Best = &F;
        if (Best)
        {
            TArray<FString> Keys = {FString::Printf(TEXT("c:%d:%d"), CircuitOf(Day), Race.Distance)};
            if (Event && Event->bGrandPrix) Keys.Add(FString::Printf(TEXT("gp:%s:%s"), Event->Id, Race.Round == TEXT("final") ? TEXT("final") : TEXT("heats")));
            for (const FString& Key : Keys)
            {
                FRacingRecordTime* R = L.Records.FindByPredicate([&Key](const FRacingRecordTime& X) { return X.Key == Key; });
                if (R && R->TimeUs <= Best->TimeUs) continue;
                if (!R) { R = &L.Records.AddDefaulted_GetRef(); R->Key = Key; }
                R->Distance = Race.Distance;
                R->TimeUs = Best->TimeUs;
                R->HorseId = Best->HorseId;
                R->Horse = Best->HorseName;
                R->RiderId = Best->RiderId;
                R->Jockey = Best->RiderName;
                R->StableId = Best->StableId;
                R->Stable = Best->StableName;
                R->T = Day;
                R->Race = Name;
            }
        }
        // The riders (a hired jockey with no effect has no id: nothing to count).
        for (const FHRFinish& F : Race.Finishes)
        {
            if (F.RiderId.IsEmpty() || F.RiderId.Len() > HRSave::MaxIdChars) continue;
            FRacingRiderTally& T = L.Riders.FindOrAdd(F.RiderId);
            if (!F.RiderName.IsEmpty()) T.Name = F.RiderName;
            T.Rides++;
            T.Earnings = HRRules::Tally(T.Earnings, F.Gross);
            // A heat is a ride, never a win, and it neither ends nor extends a streak (as HRRules counts wins).
            if (bHeat) continue;
            if (F.Place == 1)
            {
                T.Wins++;
                if (Race.Round == TEXT("final")) T.GpWins++;
                T.BestStreak = FMath::Max(T.BestStreak, ++T.Streak);
            }
            else T.Streak = 0;
        }
    }
    if (bChanged) ++L.Revision;
    return bChanged;
}

// ------------------------------------------------------------------------------------------------------------ tallies

bool RacingRecords::IsArchived(const FHRRider& R, int32 T)
{
    return R.RetiredT >= 0 && T >= R.RetiredT + HRClock::ArchiveDays;
}

int32 RacingRecords::LongestStreak(const TArray<FHRCareerLine>& Career)
{
    int32 Best = 0, Run = 0;
    for (const FHRCareerLine& Line : Career)
    {
        if (HRRules::IsHeatRound(Line.Round)) continue;
        Run = Line.Place == 1 ? Run + 1 : 0;
        Best = FMath::Max(Best, Run);
    }
    return Best;
}

int32 RacingRecords::FTally::Value(ERacingHonour H) const
{
    switch (H)
    {
        case ERacingHonour::Wins: return Wins;
        case ERacingHonour::Defeats: return Defeats;
        case ERacingHonour::GrandPrix: return GrandPrix;
        case ERacingHonour::Earnings: return Earnings;
        default: return Streak;
    }
}

TArray<RacingRecords::FTally> RacingRecords::Tallies(const FHRWorldState& S, const FRacingLedger& L, ERacingHallKind Kind)
{
    using namespace RacingRecordsText;
    TArray<FTally> Out;
    if (Kind == ERacingHallKind::Horse)
    {
        for (const TPair<FString, FHRHorse>& P : S.Horses)
        {
            const FHRHorse& H = P.Value;
            if (H.Placement == TEXT("offer") || H.OwnerId == TEXT("market")) continue;
            FTally& T = Out.AddDefaulted_GetRef();
            T.Subject = TEXT("horse:") + H.Id;
            T.Name = H.Name;
            T.Detail = StableName(S, H.OwnerId);
            T.Starts = H.Starts;
            T.Wins = H.Wins;
            T.Defeats = FMath::Max(0, H.Starts - H.Wins);
            T.GrandPrix = H.GpWins;
            T.Earnings = H.Earnings;
            T.Streak = LongestStreak(H.Career);
            T.bArchived = H.Placement == TEXT("archive");
            T.ArchivedT = T.bArchived ? H.BreedingUntilT : -1;
        }
    }
    else if (Kind == ERacingHallKind::Jockey)
    {
        for (const TPair<FString, FHRRider>& P : S.Riders)
        {
            const FHRRider& R = P.Value;
            const FRacingRiderTally* Ledger = L.Riders.Find(R.Id);
            FTally& T = Out.AddDefaulted_GetRef();
            T.Subject = TEXT("jockey:") + R.Id;
            T.Name = R.FullName();
            T.Detail = R.IsRetired() ? FString(TEXT("retraité")) : R.OwnerId.IsEmpty() ? FString(TEXT("libre")) : StableName(S, R.OwnerId);
            T.Starts = R.Rides;
            T.Wins = R.Wins;
            T.Defeats = FMath::Max(0, R.Rides - R.Wins);
            T.GrandPrix = Ledger ? Ledger->GpWins : 0;
            T.Earnings = Ledger ? Ledger->Earnings : 0;
            T.Streak = Ledger ? Ledger->BestStreak : 0;
            T.bArchived = IsArchived(R, S.T);
            T.ArchivedT = T.bArchived ? R.RetiredT + HRClock::ArchiveDays : -1;
        }
        // Players who rode: the rules keep their skill, the ledger their record.
        for (const TPair<FString, FRacingRiderTally>& P : L.Riders)
        {
            if (!P.Key.StartsWith(TEXT("player:"))) continue;
            const FRacingRiderTally& R = P.Value;
            FTally& T = Out.AddDefaulted_GetRef();
            T.Subject = TEXT("jockey:") + P.Key;
            T.Name = R.Name.IsEmpty() ? P.Key.Mid(7) : R.Name;
            const FHRStable* St = HRRules::PlayerStable(S, P.Key.Mid(7));
            T.Detail = St ? FString::Printf(TEXT("cavalier, %s"), *St->Name) : FString(TEXT("cavalier"));
            T.Starts = R.Rides;
            T.Wins = R.Wins;
            T.Defeats = FMath::Max(0, R.Rides - R.Wins);
            T.GrandPrix = R.GpWins;
            T.Earnings = R.Earnings;
            T.Streak = R.BestStreak;
        }
    }
    else
    {
        // A stable's record is its horses' careers (each line says which stable it ran for): one race counts once, won
        // when one of its runners won it; heats are runs, never wins.
        struct FRun { int32 T; int32 Order; bool bHeat; bool bWon; };
        TMap<FString, TMap<FString, FRun>> Runs;
        for (const TPair<FString, FHRHorse>& P : S.Horses)
            for (const FHRCareerLine& Line : P.Value.Career)
            {
                if (Line.StableId.IsEmpty()) continue;
                FRun& R = Runs.FindOrAdd(Line.StableId).FindOrAdd(FString::Printf(TEXT("%d:%s"), Line.T, *Line.RaceKey));
                R.T = Line.T;
                R.Order = Order(Line.RaceKey);
                R.bHeat = HRRules::IsHeatRound(Line.Round);
                R.bWon |= Line.Place == 1 && !R.bHeat;
            }
        for (const FHRStable& St : S.Stables)
        {
            FTally& T = Out.AddDefaulted_GetRef();
            T.Subject = TEXT("stable:") + St.Id;
            T.Name = St.Name;
            const FHRPlayer* Owner = St.IsPlayerOwned() ? HRRules::FindPlayer(S, St.OwnerPlayerId) : nullptr;
            T.Detail = Owner ? FString::Printf(TEXT("écurie de %s"), *Owner->Name) : St.bForSale ? FString(TEXT("à vendre")) : FString(TEXT("écurie du monde"));
            T.GrandPrix = St.GpTitles.Num();
            T.Earnings = St.TotalEarnings;
            if (const TMap<FString, FRun>* Mine = Runs.Find(St.Id))
            {
                TArray<FRun> List;
                Mine->GenerateValueArray(List);
                List.Sort([](const FRun& A, const FRun& B) { return A.T != B.T ? A.T < B.T : A.Order < B.Order; });
                int32 Run = 0;
                for (const FRun& R : List)
                {
                    T.Starts++;
                    if (R.bWon) T.Wins++;
                    if (R.bHeat) continue;
                    Run = R.bWon ? Run + 1 : 0;
                    T.Streak = FMath::Max(T.Streak, Run);
                }
                T.Defeats = T.Starts - T.Wins;
            }
        }
    }
    return Out;
}

namespace RacingRecordsText
{
    void SortBy(TArray<RacingRecords::FTally>& List, ERacingHonour H)
    {
        List.RemoveAll([H](const RacingRecords::FTally& T) { return T.Value(H) <= 0; });
        List.Sort([H](const RacingRecords::FTally& A, const RacingRecords::FTally& B)
        {
            const int32 VA = A.Value(H), VB = B.Value(H);
            if (VA != VB) return VA > VB;
            if (A.Name != B.Name) return A.Name < B.Name;
            return A.Subject < B.Subject;
        });
    }
}

TArray<RacingRecords::FTally> RacingRecords::Ranking(const FHRWorldState& S, const FRacingLedger& L, ERacingHallKind Kind, ERacingHonour Honour)
{
    TArray<FTally> List = Tallies(S, L, Kind);
    RacingRecordsText::SortBy(List, Honour);
    return List;
}

const TArray<RacingRecords::FPanel>& RacingRecords::Panels()
{
    static const TArray<FPanel> List = []
    {
        TArray<FPanel> Out;
        for (int32 C = 0; C < 3; ++C) Out.Add({C, FString(), CircuitName(C)});
        for (const HRContent::FEvent& E : HRContent::Events())
            if (E.bGrandPrix) Out.Add({-1, E.Id, E.Name});
        return Out;
    }();
    return List;
}

// ------------------------------------------------------------------------------------------------------------ pages

FString RacingRecords::Refusal(const FRacingRecordsQuery& Q)
{
    if (Q.Object >= uint8(ERacingHallObject::Count) || Q.Kind >= uint8(ERacingHallKind::Count) || Q.Sort > 2 || Q.Page < 0 || Q.Page > 100000 ||
        Q.Search.Len() > 32 || Q.Subject.Len() > HRSave::MaxIdChars + 8)
        return TEXT("Cette demande n'est pas valable.");
    if (Q.Object == uint8(ERacingHallObject::Record) && Q.Index >= Panels().Num()) return TEXT("Ce registre n'existe pas.");
    if (Q.Object == uint8(ERacingHallObject::Honour) && Q.Index >= uint8(ERacingHonour::Count)) return TEXT("Ce tableau n'existe pas.");
    return FString();
}

namespace RacingRecordsText
{
    using FLine = FRacingRecordsLine;
    FLine Heading(const FString& Text) { FLine L; L.Left = Text; L.bHeading = true; return L; }
    FLine Row(const FString& Left, const FString& Right, const FString& Sub = FString(), const FString& Subject = FString())
    {
        FLine L; L.Left = Left; L.Right = Right; L.Sub = Sub; L.Subject = Subject; return L;
    }

    /** Records held by a horse (or ridden by a rider, or set by a stable's runner). */
    void HeldRecords(const FRacingLedger& L, TFunctionRef<bool(const FRacingRecordTime&)> Mine, TArray<FLine>& Out)
    {
        TArray<const FRacingRecordTime*> Held;
        for (const FRacingRecordTime& R : L.Records) if (Mine(R)) Held.Add(&R);
        if (Held.IsEmpty()) return;
        Out.Add(Heading(TEXT("Records détenus")));
        for (const FRacingRecordTime* R : Held)
        {
            FString Where;
            if (R->Key.StartsWith(TEXT("c:"))) Where = FString::Printf(TEXT("%s, %d m"), RacingRecords::CircuitName(FCString::Atoi(*R->Key.Mid(2))), R->Distance);
            else
            {
                TArray<FString> Parts;
                R->Key.ParseIntoArray(Parts, TEXT(":"));
                const HRContent::FEvent* E = Parts.Num() > 1 ? HRContent::FindEvent(Parts[1]) : nullptr;
                Where = FString::Printf(TEXT("%s, %s"), E ? E->Name : TEXT("Grand Prix"), Parts.Num() > 2 && Parts[2] == TEXT("final") ? TEXT("finale") : TEXT("manches"));
            }
            Out.Add(Row(Where, RacingRecords::Time(R->TimeUs), R->Horse + TEXT(" · ") + RacingRecords::Date(R->T)));
        }
    }

    void Totals(const RacingRecords::FTally& T, TArray<FLine>& Out, const TCHAR* Starts)
    {
        Out.Add(Row(Starts, Number(T.Starts)));
        Out.Add(Row(TEXT("Victoires"), Number(T.Wins)));
        Out.Add(Row(TEXT("Défaites"), Number(T.Defeats), TEXT("Courses courues sans gagner, manches comprises")));
        Out.Add(Row(TEXT("Grands Prix gagnés"), Number(T.GrandPrix)));
        Out.Add(Row(TEXT("Gains"), Plural(T.Earnings, TEXT("pièce"), TEXT("pièces"))));
        Out.Add(Row(TEXT("Plus longue série"), FString::Printf(TEXT("%d victoire%s de suite"), T.Streak, T.Streak > 1 ? TEXT("s") : TEXT(""))));
    }

    /** One card: a horse, a jockey or a stable. False when the subject is unknown. */
    bool Card(const FHRWorldState& S, const FRacingLedger& L, const FString& Subject, FRacingRecordsPage& Out, TArray<FLine>& Lines)
    {
        FString Kind, Id;
        if (!Subject.Split(TEXT(":"), &Kind, &Id) || Id.IsEmpty()) return false;
        if (Kind == TEXT("horse"))
        {
            const FHRHorse* H = S.Horses.Find(Id);
            if (!H) return false;
            Out.Kicker = TEXT("FICHE · CHEVAL");
            Out.Title = H->Name;
            const FString Status = H->Placement == TEXT("archive") ? TEXT("aux archives") : H->IsRetired() ? TEXT("retraité des courses")
                : H->Injury.bActive ? TEXT("blessé") : H->Placement == TEXT("pasture") ? TEXT("au pré") : TEXT("en course");
            Out.Intro = FString::Printf(TEXT("%s · %s · %s · %s"), H->bMare ? TEXT("Jument") : TEXT("Étalon"), *Age(HRRules::HorseAgeMonths(*H, S.T)),
                *StableName(S, H->OwnerId), *Status);
            const TArray<RacingRecords::FTally> All = RacingRecords::Tallies(S, L, ERacingHallKind::Horse);
            if (const RacingRecords::FTally* T = All.FindByPredicate([&Subject](const RacingRecords::FTally& X) { return X.Subject == Subject; }))
                Totals(*T, Lines, TEXT("Courses"));
            Lines.Insert(Row(TEXT("Podiums"), Number(H->Podiums)), FMath::Min(2, Lines.Num()));
            HeldRecords(L, [&Id](const FRacingRecordTime& R) { return R.HorseId == Id; }, Lines);
            if (H->Owners.Num() > 1)
            {
                TArray<FString> Names;
                for (const FString& O : H->Owners) Names.Add(StableName(S, O));
                Lines.Add(Row(TEXT("Écuries"), FString(), FString::Join(Names, TEXT(" → "))));
            }
            if (H->Career.Num())
            {
                Lines.Add(Heading(TEXT("Dernières courses")));
                for (int32 I = H->Career.Num() - 1; I >= FMath::Max(0, H->Career.Num() - 12); --I)
                {
                    const FHRCareerLine& C = H->Career[I];
                    Lines.Add(Row(FString::Printf(TEXT("%s · %s"), *C.EventName, *Round(C.Round)),
                        C.Place == 1 ? FString(TEXT("1er")) : FString::Printf(TEXT("%de / %d"), C.Place, C.Runners), RacingRecords::Date(C.T)));
                }
            }
            return true;
        }
        if (Kind == TEXT("jockey"))
        {
            const TArray<RacingRecords::FTally> All = RacingRecords::Tallies(S, L, ERacingHallKind::Jockey);
            const RacingRecords::FTally* T = All.FindByPredicate([&Subject](const RacingRecords::FTally& X) { return X.Subject == Subject; });
            if (!T) return false;
            Out.Kicker = TEXT("FICHE · JOCKEY");
            Out.Title = T->Name;
            if (const FHRRider* R = S.Riders.Find(Id))
            {
                const FString Legend = HRRules::LegendTitle(R->Legend);
                Out.Intro = FString::Printf(TEXT("%s · %d ans · %s%s"), *R->Country, HRRules::RiderAgeMonths(*R, S.T) / 12,
                    T->bArchived ? TEXT("aux archives") : *T->Detail, Legend.IsEmpty() ? TEXT("") : *(TEXT(" · ") + Legend));
            }
            else Out.Intro = T->Detail;
            Totals(*T, Lines, TEXT("Montes"));
            HeldRecords(L, [&Id](const FRacingRecordTime& R) { return R.RiderId == Id; }, Lines);
            if (const FHRRider* R = S.Riders.Find(Id))
                if (R->Stables.Num())
                {
                    TArray<FString> Names;
                    for (const FString& O : R->Stables) Names.Add(StableName(S, O));
                    Lines.Add(Row(TEXT("Écuries"), FString(), FString::Join(Names, TEXT(" → "))));
                }
            return true;
        }
        if (Kind == TEXT("stable"))
        {
            const FHRStable* St = HRRules::FindStable(S, Id);
            if (!St) return false;
            const TArray<RacingRecords::FTally> All = RacingRecords::Tallies(S, L, ERacingHallKind::Stable);
            const RacingRecords::FTally* T = All.FindByPredicate([&Subject](const RacingRecords::FTally& X) { return X.Subject == Subject; });
            Out.Kicker = TEXT("FICHE · ÉCURIE");
            Out.Title = St->Name;
            Out.Intro = T ? T->Detail : FString();
            if (!St->Motto.IsEmpty()) Out.Intro += FString::Printf(TEXT(" · « %s »"), *St->Motto);
            if (T) Totals(*T, Lines, TEXT("Courses"));
            Lines.Add(Row(TEXT("Victoires cette saison"), Number(St->EventWins)));
            Lines.Add(Row(TEXT("Chevaux à l'écurie"), Number(HRRules::StableHorses(S, St->Id).Num())));
            TArray<FString> Riders;
            for (const FHRRider* R : HRRules::StableRiders(S, St->Id)) Riders.Add(R->FullName());
            if (Riders.Num()) Lines.Add(Row(TEXT("Jockeys"), FString(), FString::Join(Riders, TEXT(", "))));
            HeldRecords(L, [&Id](const FRacingRecordTime& R) { return R.StableId == Id; }, Lines);
            if (St->GpTitles.Num())
            {
                Lines.Add(Heading(TEXT("Titres")));
                for (int32 I = St->GpTitles.Num() - 1; I >= 0; --I)
                {
                    FString Season, Event;
                    St->GpTitles[I].Split(TEXT(":"), &Season, &Event);
                    const HRContent::FEvent* E = HRContent::FindEvent(Event);
                    Lines.Add(Row(E ? E->Name : *Event, FString::Printf(TEXT("saison %s"), *Season)));
                }
            }
            return true;
        }
        return false;
    }

    bool Matches(const FString& Name, const FString& Search)
    {
        if (Search.IsEmpty()) return true;
        const FString N = HRContent::NormalizeName(Name), Q = HRContent::NormalizeName(Search);
        // One letter: names starting with it (the pad's letter filter); more: any part of the name.
        return Q.Len() == 1 ? N.StartsWith(Q) : N.Contains(Q);
    }
}

void RacingRecords::BuildPage(const FHRWorldState& S, const FRacingLedger& L, double Now, const FRacingRecordsQuery& Q, FRacingRecordsPage& Out)
{
    using namespace RacingRecordsText;
    Out = FRacingRecordsPage();
    Out.Seq = Q.Seq;
    Out.Query = Q;
    Out.Error = Refusal(Q);
    if (!Out.Error.IsEmpty()) return;
    Out.Kicker = TEXT("SALLE DES COURSES");
    TArray<FLine> Lines;
    const ERacingHallKind Kind = ERacingHallKind(Q.Kind);
    if (!Q.Subject.IsEmpty())
    {
        if (!Card(S, L, Q.Subject, Out, Lines)) { Out.Error = TEXT("Aucune fiche à ce nom."); return; }
    }
    else switch (ERacingHallObject(Q.Object))
    {
        case ERacingHallObject::Board:
        {
            const HRContent::FEvent& E = HRContent::EventForT(S.T);
            Out.Title = TEXT("Tableau des courses");
            Out.Intro = FString::Printf(TEXT("%s · %s · %s"), *Date(S.T), E.Name, VenueName(int32(ARacingService::VenueForDay(S.T))));
            Lines.Add(Heading(FString::Printf(TEXT("Classement de la saison %d"), HRClock::SeasonOf(S.T) + 1)));
            TArray<const FHRStable*> Order;
            for (const FHRStable& St : S.Stables) if (!St.bForSale) Order.Add(&St);
            Order.Sort([](const FHRStable& A, const FHRStable& B)
            {
                if (A.EventWins != B.EventWins) return A.EventWins > B.EventWins;
                if (A.TotalEarnings != B.TotalEarnings) return A.TotalEarnings > B.TotalEarnings;
                return A.Id < B.Id;
            });
            for (int32 I = 0; I < Order.Num(); ++I)
                Lines.Add(Row(FString::Printf(TEXT("%d. %s"), I + 1, *Order[I]->Name), Plural(Order[I]->EventWins, TEXT("victoire"), TEXT("victoires")),
                    FString::Printf(TEXT("%s pièces gagnées en tout"), *Number(Order[I]->TotalEarnings)), TEXT("stable:") + Order[I]->Id));
            Lines.Add(Heading(TEXT("Prochaines courses")));
            for (const FHRRace& R : S.Meeting.Races)
            {
                const double Start = HRRules::RaceStartSeconds(S, R.Key);
                if (R.IsRun() || Start < 0.) continue;
                Lines.Add(Row(ARacingService::RaceName(R), Ago(Start - Now),
                    FString::Printf(TEXT("%s · %d m · %d partants"), VenueName(int32(ARacingService::VenueForDay(S.T))), R.Distance, R.Entries.Num())));
            }
            for (int32 D = 1; D <= 3; ++D)
            {
                const HRContent::FEvent& Next = HRContent::EventForT(S.T + D);
                Lines.Add(Row(Next.Name, D == 1 ? FString(TEXT("demain")) : FString::Printf(TEXT("dans %d jours"), D),
                    FString::Printf(TEXT("%s · %s%s"), VenueName(int32(ARacingService::VenueForDay(S.T + D))), *Date(S.T + D), Next.bGrandPrix ? TEXT(" · Grand Prix") : TEXT(""))));
            }
            break;
        }
        case ERacingHallObject::Record:
        {
            const FPanel& P = Panels()[Q.Index];
            Out.Kicker = TEXT("SALLE DES COURSES · RECORDS");
            Out.Title = P.Name;
            if (P.Circuit >= 0)
            {
                const FString Prefix = FString::Printf(TEXT("c:%d:"), P.Circuit);
                TArray<const FRacingRecordTime*> Held;
                for (const FRacingRecordTime& R : L.Records) if (R.Key.StartsWith(Prefix)) Held.Add(&R);
                Held.Sort([](const FRacingRecordTime& A, const FRacingRecordTime& B) { return A.Distance < B.Distance; });
                Out.Intro = Held.IsEmpty() ? FString(TEXT("Aucun record encore : les temps sont notés à mesure que les courses sont courues."))
                    : FString::Printf(TEXT("Meilleur temps à chaque distance, depuis la %s"), *Date(FMath::Max(0, L.SinceT)));
                for (const FRacingRecordTime* R : Held)
                    Lines.Add(Row(FString::Printf(TEXT("%d m · %s"), R->Distance, *Time(R->TimeUs)), R->Horse,
                        FString::Printf(TEXT("%s · %s · %s"), R->Jockey.IsEmpty() ? TEXT("jockey loué") : *R->Jockey, *R->Stable, *Date(R->T)), TEXT("horse:") + R->HorseId));
            }
            else
            {
                const HRContent::FEvent* E = HRContent::FindEvent(P.EventId);
                Out.Intro = E ? FString::Printf(TEXT("Grand Prix · finale sur %d m · %s"), E->FinalDistance, E->Runs > 1 ? TEXT("deux manches, le meilleur temps compte")
                    : E->bSprintQualifiers ? TEXT("sprints qualificatifs") : TEXT("manches puis finale")) : FString();
                Lines.Add(Heading(TEXT("Records")));
                for (const TCHAR* Round : {TEXT("final"), TEXT("heats")})
                {
                    const FRacingRecordTime* R = L.Find(FString::Printf(TEXT("gp:%s:%s"), *P.EventId, Round));
                    const TCHAR* What = FCString::Strcmp(Round, TEXT("final")) == 0 ? TEXT("Finale") : TEXT("Manches");
                    if (R)
                        Lines.Add(Row(FString::Printf(TEXT("%s · %d m · %s"), What, R->Distance, *Time(R->TimeUs)), R->Horse,
                            FString::Printf(TEXT("%s · %s · %s"), R->Jockey.IsEmpty() ? TEXT("jockey loué") : *R->Jockey, *R->Stable, *Date(R->T)), TEXT("horse:") + R->HorseId));
                    else Lines.Add(Row(What, TEXT("—"), TEXT("Pas encore couru depuis l'ouverture de la salle")));
                }
                // Its winners, from the horses' careers (the rules' whole history).
                struct FWin { int32 T; FString HorseId, Horse, Stable; };
                TArray<FWin> Wins;
                if (E)
                    for (const TPair<FString, FHRHorse>& H : S.Horses)
                        for (const FHRCareerLine& C : H.Value.Career)
                            if (C.Round == TEXT("final") && C.Place == 1 && C.EventName == E->Name)
                                Wins.Add({C.T, H.Key, H.Value.Name, StableName(S, C.StableId)});
                Wins.Sort([](const FWin& A, const FWin& B) { return A.T > B.T; });
                Lines.Add(Heading(TEXT("Palmarès")));
                if (Wins.IsEmpty()) Lines.Add(Row(TEXT("Pas encore de vainqueur"), FString()));
                for (const FWin& W : Wins)
                    Lines.Add(Row(FString::Printf(TEXT("Saison %d"), HRClock::SeasonOf(W.T) + 1), W.Horse, W.Stable, TEXT("horse:") + W.HorseId));
            }
            break;
        }
        case ERacingHallObject::Honour:
        {
            const ERacingHonour H = ERacingHonour(Q.Index);
            Out.Kicker = FString::Printf(TEXT("TABLEAU D'HONNEUR · %s"), *Upper(KindName(Kind)));
            Out.Title = HonourName(H);
            Out.Intro = H == ERacingHonour::Defeats ? TEXT("Courses courues sans gagner, manches comprises. Les archives comptent aussi.")
                : H == ERacingHonour::Streak ? TEXT("Victoires de suite (les manches ne comptent pas). Les archives comptent aussi.")
                : TEXT("De tous les temps : les archives comptent aussi.");
            if (Kind == ERacingHallKind::Jockey && H != ERacingHonour::Wins && H != ERacingHonour::Defeats)
                Out.Intro += FString::Printf(TEXT(" Notés depuis la %s."), *Date(FMath::Max(0, L.SinceT)));
            const TArray<FTally> List = Ranking(S, L, Kind, H);
            for (int32 I = 0; I < List.Num(); ++I)
                Lines.Add(Row(FString::Printf(TEXT("%d. %s"), I + 1, *List[I].Name), Value(H, List[I].Value(H)),
                    List[I].bArchived ? List[I].Detail + TEXT(" · aux archives") : List[I].Detail, List[I].Subject));
            if (List.IsEmpty()) Out.Intro += TEXT("\nPersonne encore.");
            break;
        }
        case ERacingHallObject::Cabinet:
        case ERacingHallObject::Archive:
        {
            const bool bArchive = Q.Object == uint8(ERacingHallObject::Archive);
            Out.Kicker = bArchive ? FString::Printf(TEXT("ARCHIVES · %s"), *Upper(KindName(Kind))) : FString::Printf(TEXT("FICHIER · %s"), *Upper(KindName(Kind)));
            Out.Title = bArchive ? TEXT("Registres des archives") : TEXT("Fichier");
            TArray<FTally> List = Tallies(S, L, Kind);
            List.RemoveAll([&](const FTally& T) { return T.bArchived != bArchive || !Matches(T.Name, Q.Search); });
            if (bArchive)
                List.Sort([&Q](const FTally& A, const FTally& B)
                {
                    if (Q.Sort == 0 && A.ArchivedT != B.ArchivedT) return A.ArchivedT > B.ArchivedT;
                    return A.Name != B.Name ? A.Name < B.Name : A.Subject < B.Subject;
                });
            else
                List.Sort([&Q](const FTally& A, const FTally& B)
                {
                    if (Q.Sort == 1 && A.Wins != B.Wins) return A.Wins > B.Wins;
                    if (Q.Sort == 2 && A.Earnings != B.Earnings) return A.Earnings > B.Earnings;
                    return A.Name != B.Name ? A.Name < B.Name : A.Subject < B.Subject;
                });
            const TCHAR* Sorts[] = {bArchive ? TEXT("les plus récents d'abord") : TEXT("par nom"), bArchive ? TEXT("par nom") : TEXT("par victoires"), TEXT("par gains")};
            Out.Intro = bArchive
                ? FString::Printf(TEXT("Deux ans après la retraite, l'histoire va aux archives. %s, %s."), *Plural(List.Num(), TEXT("registre"), TEXT("registres")), Sorts[FMath::Min<int32>(Q.Sort, 1)])
                : FString::Printf(TEXT("%s, %s."), *Plural(List.Num(), TEXT("fiche"), TEXT("fiches")), Sorts[Q.Sort]);
            if (!Q.Search.IsEmpty()) Out.Intro += FString::Printf(TEXT(" Recherche : « %s »."), *Q.Search);
            for (const FTally& T : List)
            {
                const FString Right = bArchive ? FString::Printf(TEXT("archivé %s"), *Date(FMath::Max(0, T.ArchivedT)))
                    : Q.Sort == 2 ? Plural(T.Earnings, TEXT("pièce"), TEXT("pièces")) : Plural(T.Wins, TEXT("victoire"), TEXT("victoires"));
                Lines.Add(Row(T.Name, Right, FString::Printf(TEXT("%s · %d course%s"), *T.Detail, T.Starts, T.Starts > 1 ? TEXT("s") : TEXT("")), T.Subject));
            }
            break;
        }
        default:
            Out.Title = TEXT("Salle des courses");
            Out.Intro = TEXT("Les registres de la Mairie de Belmonte : tout ce que les courses ont écrit, à Hidamari comme à Belmonte.");
            Lines.Add(Row(TEXT("Tableau des courses"), TEXT("au-dessus de la porte"), TEXT("Le classement de la saison et les prochaines courses")));
            Lines.Add(Row(TEXT("Records"), TEXT("entre les portes"), TEXT("Un panneau par piste et par Grand Prix")));
            Lines.Add(Row(TEXT("Tableaux d'honneur"), TEXT("aux deux bouts"), TEXT("Victoires, défaites, Grands Prix, gains, séries")));
            Lines.Add(Row(TEXT("Fichier"), TEXT("à droite"), TEXT("Une fiche par cheval, jockey et écurie")));
            Lines.Add(Row(TEXT("Archives"), TEXT("à gauche"), TEXT("L'histoire de plus de deux ans")));
            break;
    }
    Out.Total = Lines.Num();
    Out.Pages = FMath::Max(1, FMath::DivideAndRoundUp(Lines.Num(), PageLines));
    Out.Page = FMath::Clamp(Q.Page, 0, Out.Pages - 1);
    for (int32 I = Out.Page * PageLines; I < FMath::Min(Lines.Num(), (Out.Page + 1) * PageLines); ++I) Out.Lines.Add(Lines[I]);
}

void RacingRecords::BuildBoards(const FHRWorldState& S, const FRacingLedger& L, double Now, FRacingHallBoards& Out)
{
    using namespace RacingRecordsText;
    Out = FRacingHallBoards();
    Out.Day = S.T;
    // The split-flap board: the season's standings and the next races, upper case as the flaps are.
    {
        TArray<const FHRStable*> Order;
        for (const FHRStable& St : S.Stables) if (!St.bForSale) Order.Add(&St);
        Order.Sort([](const FHRStable& A, const FHRStable& B)
        {
            if (A.EventWins != B.EventWins) return A.EventWins > B.EventWins;
            if (A.TotalEarnings != B.TotalEarnings) return A.TotalEarnings > B.TotalEarnings;
            return A.Id < B.Id;
        });
        TArray<FString> Rows = {FString::Printf(TEXT("CLASSEMENT  SAISON %d"), HRClock::SeasonOf(S.T) + 1)};
        for (int32 I = 0; I < FMath::Min(6, Order.Num()); ++I)
            Rows.Add(FString::Printf(TEXT("%d  %s   %d V"), I + 1, *Upper(Order[I]->Name), Order[I]->EventWins));
        Out.Standings = Latin1(FString::Join(Rows, TEXT("\n")));
        Rows = {TEXT("PROCHAINES COURSES")};
        const TCHAR* Venue = VenueName(int32(ARacingService::VenueForDay(S.T)));
        for (const FHRRace& R : S.Meeting.Races)
        {
            const double Start = HRRules::RaceStartSeconds(S, R.Key);
            if (R.IsRun() || Start < 0. || Rows.Num() >= 5) continue;
            Rows.Add(FString::Printf(TEXT("%s  %s  %s"), *Upper(Ago(Start - Now)), *Upper(Venue), *Upper(ARacingService::RaceName(R))));
        }
        for (int32 D = 1; Rows.Num() < 7; ++D)
        {
            const HRContent::FEvent& Next = HRContent::EventForT(S.T + D);
            Rows.Add(FString::Printf(TEXT("J+%d  %s  %s%s"), D, *Upper(VenueName(int32(ARacingService::VenueForDay(S.T + D)))), *Upper(Next.Name),
                Next.bGrandPrix ? TEXT("  GP") : TEXT("")));
        }
        Out.Upcoming = Latin1(FString::Join(Rows, TEXT("\n")));
    }
    // The record panels.
    for (const FPanel& P : Panels())
    {
        TArray<FString> Rows;
        if (P.Circuit >= 0)
        {
            Rows.Add(TEXT("RECORDS"));
            Rows.Add(Upper(P.Name));
            TArray<const FRacingRecordTime*> Held;
            const FString Prefix = FString::Printf(TEXT("c:%d:"), P.Circuit);
            for (const FRacingRecordTime& R : L.Records) if (R.Key.StartsWith(Prefix)) Held.Add(&R);
            Held.Sort([](const FRacingRecordTime& A, const FRacingRecordTime& B) { return A.Distance < B.Distance; });
            Rows.Add(FString());
            for (int32 I = 0; I < FMath::Min(5, Held.Num()); ++I)
                Rows.Add(FString::Printf(TEXT("%d m  %s  %s"), Held[I]->Distance, *Time(Held[I]->TimeUs), *Held[I]->Horse));
            if (Held.IsEmpty()) Rows.Add(TEXT("(aucun temps encore)"));
        }
        else
        {
            Rows.Add(TEXT("GRAND PRIX"));
            Rows.Add(Upper(P.Name));
            Rows.Add(FString());
            const FRacingRecordTime* F = L.Find(FString::Printf(TEXT("gp:%s:final"), *P.EventId));
            const FRacingRecordTime* H = L.Find(FString::Printf(TEXT("gp:%s:heats"), *P.EventId));
            Rows.Add(F ? FString::Printf(TEXT("Finale  %s  %s"), *Time(F->TimeUs), *F->Horse) : FString(TEXT("Finale  -")));
            Rows.Add(H ? FString::Printf(TEXT("Manches  %s  %s"), *Time(H->TimeUs), *H->Horse) : FString(TEXT("Manches  -")));
            // The last winner, from the careers.
            const HRContent::FEvent* E = HRContent::FindEvent(P.EventId);
            int32 BestT = -1;
            FString Winner;
            if (E)
                for (const TPair<FString, FHRHorse>& Horse : S.Horses)
                    for (const FHRCareerLine& C : Horse.Value.Career)
                        if (C.Round == TEXT("final") && C.Place == 1 && C.EventName == E->Name && C.T > BestT) { BestT = C.T; Winner = Horse.Value.Name; }
            Rows.Add(BestT >= 0 ? FString::Printf(TEXT("Tenant : %s (saison %d)"), *Winner, HRClock::SeasonOf(BestT) + 1) : FString(TEXT("Tenant : -")));
        }
        Out.Records.Add(Latin1(FString::Join(Rows, TEXT("\n"))));
    }
    // The honour boards: the top three of each kind.
    TArray<FTally> Kinds[3];
    for (int32 K = 0; K < 3; ++K) Kinds[K] = Tallies(S, L, ERacingHallKind(K));
    for (int32 H = 0; H < int32(ERacingHonour::Count); ++H)
    {
        TArray<FString> Rows = {Upper(HonourName(ERacingHonour(H)))};
        for (int32 K = 0; K < 3; ++K)
        {
            TArray<FTally> List = Kinds[K];
            SortBy(List, ERacingHonour(H));
            Rows.Add(FString());
            Rows.Add(Upper(KindName(ERacingHallKind(K))));
            for (int32 I = 0; I < 3; ++I)
                Rows.Add(List.IsValidIndex(I) ? FString::Printf(TEXT("%d. %s  %s"), I + 1, *List[I].Name, *Short(ERacingHonour(H), List[I].Value(ERacingHonour(H))))
                    : FString::Printf(TEXT("%d. -"), I + 1));
        }
        Out.Honours.Add(Latin1(FString::Join(Rows, TEXT("\n"))));
    }
    int32 Cards[3] = {0, 0, 0}, Archived[2] = {0, 0};
    for (int32 K = 0; K < 3; ++K)
        for (const FTally& T : Kinds[K]) (T.bArchived ? Archived[FMath::Min(K, 1)] : Cards[K])++;
    Out.Cabinet = Latin1(FString::Printf(TEXT("FICHIER\n%d chevaux · %d jockeys · %d écuries"), Cards[0], Cards[1], Cards[2]));
    Out.Archive = Latin1(FString::Printf(TEXT("ARCHIVES\n%d chevaux · %d jockeys"), Archived[0], Archived[1]));
}

// ------------------------------------------------------------------------------------------------------------ the hall's places

bool RacingRecords::HallAnchors(const TSharedPtr<FJsonObject>& Places, const FVector& OriginCm, TArray<FAnchor>& Out, FVector& OutCentre)
{
    // Derived from the Palazzo Comunale's committed placement by world/regions/belmonte/build.py (RECORDS_HALL):
    // Belmonte-local cm round the region's origin, as the TVs; no hardcoded fallback.
    Out.Reset();
    const TSharedPtr<FJsonObject>* Hall = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Rows = nullptr;
    FVector Centre;
    double Floor = 0.;
    if (!Places || !Places->TryGetObjectField(TEXT("records_hall"), Hall) || !Hall ||
        !RacingPlaces::Vector(*Hall, TEXT("centre_cm"), Centre) || !RacingPlaces::Number(*Hall, TEXT("floor_cm"), Floor) ||
        !(*Hall)->TryGetArrayField(TEXT("objects"), Rows) || !Rows)
        return false;
    static const TCHAR* const Names[] = {TEXT("board"), TEXT("record"), TEXT("honour"), TEXT("cabinet"), TEXT("archive"), TEXT("plaque")};
    static_assert(UE_ARRAY_COUNT(Names) == int32(ERacingHallObject::Count), "one name per hall object");
    TArray<FAnchor> Parsed;
    int32 Seen[int32(ERacingHallObject::Count)] = {};
    for (const TSharedPtr<FJsonValue>& Row : *Rows)
    {
        const TSharedPtr<FJsonObject>* O = nullptr;
        FString Name;
        FVector At;
        double Yaw = 0., Index = 0.;
        const TArray<TSharedPtr<FJsonValue>>* Size = nullptr;
        if (!Row.IsValid() || !Row->TryGetObject(O) || !O || !(*O)->TryGetStringField(TEXT("object"), Name) ||
            !RacingPlaces::Number(*O, TEXT("index"), Index) || !RacingPlaces::Vector(*O, TEXT("at_cm"), At) ||
            !RacingPlaces::Number(*O, TEXT("yaw"), Yaw) || !(*O)->TryGetArrayField(TEXT("size_cm"), Size) || !Size || Size->Num() != 2)
            return false;
        int32 Object = INDEX_NONE;
        for (int32 K = 0; K < int32(UE_ARRAY_COUNT(Names)); ++K) if (Name == Names[K]) Object = K;
        if (Object == INDEX_NONE || Index < 0. || Index > 15.) return false;
        FAnchor& A = Parsed.AddDefaulted_GetRef();
        A.Object = ERacingHallObject(Object);
        A.Index = uint8(Index);
        A.At = FTransform(FRotator(0., Yaw, 0.), OriginCm + At);
        A.Size = FVector2D((*Size)[0]->AsNumber(), (*Size)[1]->AsNumber());
        A.Floor = OriginCm.Z + Floor;
        if (!FMath::IsFinite(A.Size.X) || !FMath::IsFinite(A.Size.Y) || A.Size.X <= 0. || A.Size.Y <= 0.) return false;
        ++Seen[Object];
    }
    // The hall's objects: one board, the seven records, five honour boards, the cabinet, the archive and the plaque.
    if (Seen[int32(ERacingHallObject::Board)] != 1 || Seen[int32(ERacingHallObject::Record)] != 7 ||
        Seen[int32(ERacingHallObject::Honour)] != 5 || Seen[int32(ERacingHallObject::Cabinet)] != 1 ||
        Seen[int32(ERacingHallObject::Archive)] != 1 || Seen[int32(ERacingHallObject::Plaque)] != 1)
        return false;
    Out = MoveTemp(Parsed);
    OutCentre = OriginCm + Centre;
    return true;
}

int32 RacingRecords::AnchorInReach(const TArray<FAnchor>& Anchors, const FVector& Location, const FVector& Facing)
{
    int32 Best = INDEX_NONE;
    double BestDistance = 0.;
    for (int32 I = 0; I < Anchors.Num(); ++I)
    {
        const FAnchor& A = Anchors[I];
        const FVector L = A.At.InverseTransformPositionNoScale(Location);
        const double Above = Location.Z - A.Floor;
        // In front of it, within reach (a little further for the high split-flap board), beside it, on the hall's floor.
        const double Reach = A.Object == ERacingHallObject::Board ? 380. : 240.;
        if (L.X < 20. || L.X > Reach || FMath::Abs(L.Y) > A.Size.X * .5 + 40. || Above < -40. || Above > 240.) continue;
        // A reader facing a direction reads what lies that way (in a corner two objects are within reach).
        const FVector Toward = (A.At.GetLocation() - Location).GetSafeNormal2D();
        if (!Facing.IsNearlyZero() && FVector::DotProduct(Facing.GetSafeNormal2D(), Toward) < .2) continue;
        const double D = L.X + FMath::Abs(L.Y) - (Facing.IsNearlyZero() ? 0. : 200. * FVector::DotProduct(Facing.GetSafeNormal2D(), Toward));
        if (Best == INDEX_NONE || D < BestDistance) { Best = I; BestDistance = D; }
    }
    return Best;
}

FRacingRecordsQuery RacingRecords::FirstQuery(const FAnchor& A)
{
    FRacingRecordsQuery Q;
    Q.Object = uint8(A.Object);
    Q.Index = A.Index;
    return Q;
}

// ------------------------------------------------------------------------------------------------------------ desk

URacingRecordsDesk::URacingRecordsDesk()
{
    PrimaryComponentTick.bCanEverTick = false;
    SetIsReplicatedByDefault(true);
}

void URacingRecordsDesk::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
    Super::GetLifetimeReplicatedProps(OutLifetimeProps);
    // What a player reads is theirs alone, and only while they read it.
    DOREPLIFETIME_CONDITION(URacingRecordsDesk, Page, COND_OwnerOnly);
    DOREPLIFETIME_CONDITION(URacingRecordsDesk, Boards, COND_OwnerOnly);
}

void URacingRecordsDesk::BeginPlay()
{
    Super::BeginPlay();
    if (GetWorld() && GetNetMode() != NM_DedicatedServer) ARacingRecordsHall::Ensure(GetWorld());
}

URacingRecordsDesk* URacingRecordsDesk::Of(const AController* Controller)
{
    return Controller ? Controller->FindComponentByClass<URacingRecordsDesk>() : nullptr;
}

URacingRecordsDesk* URacingRecordsDesk::Local(const UObject* WorldContext)
{
    const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
    return World ? Of(World->GetFirstPlayerController()) : nullptr;
}

void URacingRecordsDesk::SetInHall(bool bOn)
{
    if (bOn == bInHallAsked) return;
    bInHallAsked = bOn;
    const AActor* Owner = GetOwner();
    if (!Owner) return;
    if (Owner->HasAuthority()) ServerSetInHall_Implementation(bOn);
    else ServerSetInHall(bOn);
}

void URacingRecordsDesk::ServerSetInHall_Implementation(bool bOn)
{
    bInHall = bOn;
    // Nothing is kept for a player away from the hall.
    if (!bOn) HostSetBoards(FRacingHallBoards());
    else if (ARacingService* Service = ARacingService::Find(this)) Service->RefreshWallets();
}

uint32 URacingRecordsDesk::Ask(FRacingRecordsQuery Query)
{
    const double Now = FPlatformTime::Seconds();
    if (LastAsk >= 0. && Now - LastAsk < MinAskGap) return 0;
    const AActor* Owner = GetOwner();
    if (!Owner) return 0;
    LastAsk = Now;
    Query.Seq = NextSeq++;
    PendingSeq = Query.Seq;
    if (Owner->HasAuthority()) HostHandle(Query, ARacingService::Find(this));
    else ServerAsk(Query);
    return Query.Seq;
}

void URacingRecordsDesk::ServerAsk_Implementation(const FRacingRecordsQuery& Query)
{
    // A client asks at most every MinAskGap; a faster stream is answered with a refusal, never built.
    const double Now = FPlatformTime::Seconds();
    if (LastServed >= 0. && Now - LastServed < MinAskGap * .5)
    {
        FRacingRecordsPage Busy;
        Busy.Seq = Query.Seq;
        Busy.Query = Query;
        Busy.Error = TEXT("Un instant, le greffier tourne les pages.");
        Page = Busy;
        ++Revision;
        return;
    }
    LastServed = Now;
    HostHandle(Query, ARacingService::Find(this));
}

void URacingRecordsDesk::HostHandle(const FRacingRecordsQuery& Query, ARacingService* Service)
{
    FRacingRecordsPage Next;
    Next.Seq = Query.Seq;
    Next.Query = Query;
    Next.Error = RacingRecords::Refusal(Query);
    if (Next.Error.IsEmpty())
    {
        if (!Service || !Service->HasWorld()) Next.Error = TEXT("La salle des courses est fermée pour le moment.");
        else Service->BuildRecordsPage(Query, Next);
    }
    Page = Next;
    // On the host (and offline) the owner reads it at once.
    OnRep_Page();
}

void URacingRecordsDesk::HostSetBoards(const FRacingHallBoards& Next)
{
    if (FRacingHallBoards::StaticStruct()->CompareScriptStruct(&Next, &Boards, PPF_None)) return;
    Boards = Next;
    ++Revision;
}

void URacingRecordsDesk::OnRep_Page()
{
    if (PendingSeq && Page.Seq >= PendingSeq) PendingSeq = 0;
    ++Revision;
}

void URacingRecordsDesk::OnRep_Boards() { ++Revision; }

// ------------------------------------------------------------------------------------------------------------ the hall's objects

ARacingRecordsHall::ARacingRecordsHall()
{
    PrimaryActorTick.bCanEverTick = true;
    SetActorTickInterval(.25f);
    bReplicates = false;
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    static ConstructorHelpers::FObjectFinder<UMaterialInterface> Basic(TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
    BackMaterial = Basic.Object;
}

ARacingRecordsHall* ARacingRecordsHall::Find(const UObject* WorldContext)
{
    UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
    if (!World) return nullptr;
    TActorIterator<ARacingRecordsHall> It(World);
    return It ? *It : nullptr;
}

ARacingRecordsHall* ARacingRecordsHall::Ensure(UWorld* World)
{
    if (!World || World->GetNetMode() == NM_DedicatedServer) return nullptr;
    if (ARacingRecordsHall* Existing = Find(World)) return Existing;
    FActorSpawnParameters Params;
    Params.ObjectFlags |= RF_Transient;
    return World->SpawnActor<ARacingRecordsHall>(Params);
}

void ARacingRecordsHall::EndPlay(const EEndPlayReason::Type Reason)
{
    RacingRecords::Close();
    Clear();
    Super::EndPlay(Reason);
}

void ARacingRecordsHall::Clear()
{
    for (UStaticMeshComponent* C : Meshes) if (C) C->DestroyComponent();
    for (UTextRenderComponent* C : Texts) if (C) C->DestroyComponent();
    Meshes.Reset();
    Texts.Reset();
    TextAnchor.Reset();
    Written = MAX_uint32;
}

void ARacingRecordsHall::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    if (Anchors.IsEmpty())
    {
        FVector Origin;
        if (!RacingCounter::RegionOrigin(this, Origin) || !RacingRecords::HallAnchors(RacingPlaces::Belmonte(), Origin, Anchors, Centre)) return;
    }
    URacingRecordsDesk* Desk = URacingRecordsDesk::Local(this);
    const APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
    const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
    const bool bNear = Pawn && FVector::DistSquared(Centre, Pawn->GetActorLocation()) < FMath::Square(ShowRadius);
    if (Desk) Desk->SetInHall(bNear || RacingRecords::IsOpen());
    if (!bNear) { if (Texts.Num()) Clear(); return; }
    if (Texts.IsEmpty()) Build();
    // The boards change with the races: rewritten when their texts do, at most once a second.
    const double Real = FPlatformTime::Seconds();
    if (Desk && Desk->GetRevision() != Written && Real - LastWrite >= 1.) Write();
}

void ARacingRecordsHall::Build()
{
    using namespace RacingRecords;
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    auto Box = [&](const FTransform& At, const FVector& Centre_, const FVector& SizeCm, const FLinearColor& Color, bool bSolid)
    {
        auto* M = NewObject<UStaticMeshComponent>(this);
        M->SetupAttachment(RootComponent);
        M->SetStaticMesh(Cube);
        M->SetCollisionEnabled(bSolid ? ECollisionEnabled::QueryAndPhysics : ECollisionEnabled::NoCollision);
        if (bSolid) M->SetCollisionProfileName(TEXT("BlockAll"));
        M->SetCastShadow(bSolid);
        M->SetCanEverAffectNavigation(false);
        M->SetCullDistance(ShowRadius);
        // The cube is 1 m across round its centre.
        M->SetWorldTransform(FTransform(At.Rotator(), At.TransformPosition(Centre_), SizeCm / 100.));
        if (BackMaterial)
        {
            UMaterialInstanceDynamic* Mat = UMaterialInstanceDynamic::Create(BackMaterial, M);
            Mat->SetVectorParameterValue(TEXT("Color"), Color);
            M->SetMaterial(0, Mat);
        }
        M->RegisterComponent();
        Meshes.Add(M);
    };
    auto Label = [&](int32 Anchor, const FTransform& At, const FVector& Where, float Size, const FColor& Color, EHorizTextAligment Align, EVerticalTextAligment VAlign)
    {
        auto* T = NewObject<UTextRenderComponent>(this);
        T->SetupAttachment(RootComponent);
        T->SetWorldTransform(FTransform(At.Rotator(), At.TransformPosition(Where)));
        T->SetHorizontalAlignment(Align);
        T->SetVerticalAlignment(VAlign);
        T->SetWorldSize(Size);
        T->SetTextRenderColor(Color);
        T->SetCastShadow(false);
        T->SetCullDistance(ShowRadius);
        T->RegisterComponent();
        Texts.Add(T);
        TextAnchor.Add(Anchor);
        return T;
    };
    const FLinearColor Forest(.03f, .07f, .05f), Brass(.55f, .38f, .14f), Walnut(.12f, .06f, .03f), Flap(.012f, .012f, .014f);
    const FColor Cream(255, 238, 205), Amber(255, 196, 90), Gold(230, 200, 131);
    for (int32 I = 0; I < Anchors.Num(); ++I)
    {
        const FAnchor& A = Anchors[I];
        const double W = A.Size.X, H = A.Size.Y;
        switch (A.Object)
        {
            case ERacingHallObject::Board:
            {
                // A black split-flap board in a brass frame, two halves. Seen from the hall, the anchor's +Y is the
                // reader's left: the standings on the left, the next races on the right, each written rightwards.
                Box(A.At, FVector(-6., 0., 0.), FVector(4., W + 16., H + 16.), Brass, false);
                Box(A.At, FVector(-3.5, 0., 0.), FVector(3., W, H), Flap, false);
                Box(A.At, FVector(-1.8, 0., 0.), FVector(.4, 1.2, H - 8.), FLinearColor(.25f, .18f, .07f), false);
                Label(I, A.At, FVector(0., W * .5 - 12., H * .5 - 10.), 13.f, Amber, EHTA_Left, EVRTA_TextTop);
                Label(I, A.At, FVector(0., -12., H * .5 - 10.), 13.f, Amber, EHTA_Left, EVRTA_TextTop);
                break;
            }
            case ERacingHallObject::Record:
            case ERacingHallObject::Honour:
            case ERacingHallObject::Plaque:
            {
                const bool bPlaque = A.Object == ERacingHallObject::Plaque;
                Box(A.At, FVector(-4., 0., 0.), FVector(3., W + 8., H + 8.), Brass, false);
                Box(A.At, FVector(-2., 0., 0.), FVector(2., W, H), bPlaque ? Walnut : Forest, false);
                UTextRenderComponent* T = Label(bPlaque ? INDEX_NONE : I, A.At, FVector(0., 0., H * .5 - 7.), A.Object == ERacingHallObject::Honour ? 5.5f : 6.2f,
                    bPlaque ? Gold : Cream, EHTA_Center, EVRTA_TextTop);
                if (bPlaque)
                    T->SetText(FText::FromString(TEXT("SALLE DES COURSES\n\nRegistres de la\nMairie de Belmonte\n\nHidamari · Belmonte")));
                break;
            }
            case ERacingHallObject::Cabinet:
            {
                // A walnut card cabinet: four rows of three drawers with brass pulls; its label on the top drawer row.
                const double D = 50.;
                Box(A.At, FVector(-D * .5, 0., 0.), FVector(D, W, H), Walnut, true);
                for (int32 R = 0; R < 4; ++R)
                    for (int32 C = 0; C < 3; ++C)
                    {
                        const FVector Drawer(1., (C - 1) * (W - 10.) / 3., H * .5 - 22. - R * (H - 14.) / 4.);
                        Box(A.At, Drawer, FVector(2., (W - 10.) / 3. - 4., (H - 14.) / 4. - 4.), FLinearColor(.17f, .09f, .045f), false);
                        Box(A.At, Drawer + FVector(1.8, 0., -6.), FVector(1.5, 7., 1.5), Brass, false);
                    }
                Box(A.At, FVector(-D * .5, 0., H * .5 + 1.5), FVector(D + 4., W + 4., 3.), Walnut, false);
                // Its label on a small forest board standing on top, brass-edged.
                Box(A.At, FVector(-8., 0., H * .5 + 20.), FVector(2.5, W - 2., 34.), Brass, false);
                Box(A.At, FVector(-6.5, 0., H * .5 + 20.), FVector(1.5, W - 6., 30.), Forest, false);
                Label(I, A.At, FVector(-5.5, 0., H * .5 + 20.), 5.f, Cream, EHTA_Center, EVRTA_TextCenter);
                break;
            }
            case ERacingHallObject::Archive:
            {
                // A long table (its top 85 cm above the floor, the anchor 70 cm) with three bound ledgers and one open,
                // an apron in front carrying the label.
                const double D = 60.;
                Box(A.At, FVector(-D * .5, 0., 12.), FVector(D, W, 6.), Walnut, false);
                for (const double Y : {-W * .5 + 8., W * .5 - 8.})
                    Box(A.At, FVector(-D * .5, Y, -29.), FVector(D - 6., 6., 82.), Walnut, true);
                Box(A.At, FVector(-D * .5, 0., -40.), FVector(D - 12., W - 20., 3.), Walnut, false);
                Box(A.At, FVector(-1.5, 0., 0.), FVector(3., W - 4., 18.), FLinearColor(.17f, .09f, .045f), false);
                const FLinearColor Leather[] = {FLinearColor(.18f, .03f, .02f), FLinearColor(.04f, .09f, .05f), FLinearColor(.12f, .07f, .02f)};
                for (int32 B = 0; B < 3; ++B)
                    Box(A.At, FVector(-D * .5 - 4., -W * .5 + 22. + B * 30., 18.5), FVector(30., 24., 7.), Leather[B], false);
                Box(A.At, FVector(-D * .5 + 6., W * .5 - 26., 16.), FVector(28., 40., 2.), FLinearColor(.8f, .74f, .6f), false);
                Label(I, A.At, FVector(1., 0., 0.), 5.f, Cream, EHTA_Center, EVRTA_TextCenter);
                break;
            }
            default: break;
        }
    }
    Written = MAX_uint32;
    LastWrite = -10.;
}

void ARacingRecordsHall::Write()
{
    const URacingRecordsDesk* Desk = URacingRecordsDesk::Local(this);
    if (!Desk) return;
    Written = Desk->GetRevision();
    LastWrite = FPlatformTime::Seconds();
    const FRacingHallBoards& B = Desk->GetBoards();
    int32 BoardHalf = 0;
    for (int32 I = 0; I < Texts.Num(); ++I)
    {
        if (!TextAnchor.IsValidIndex(I) || TextAnchor[I] == INDEX_NONE || !Anchors.IsValidIndex(TextAnchor[I])) continue;
        const RacingRecords::FAnchor& A = Anchors[TextAnchor[I]];
        FString Text;
        switch (A.Object)
        {
            case ERacingHallObject::Board: Text = BoardHalf++ == 0 ? B.Standings : B.Upcoming; break;
            case ERacingHallObject::Record: Text = B.Records.IsValidIndex(A.Index) ? B.Records[A.Index] : FString(); break;
            case ERacingHallObject::Honour: Text = B.Honours.IsValidIndex(A.Index) ? B.Honours[A.Index] : FString(); break;
            case ERacingHallObject::Cabinet: Text = B.Cabinet; break;
            case ERacingHallObject::Archive: Text = B.Archive; break;
            default: continue;
        }
        if (!Texts[I]->Text.EqualTo(FText::FromString(Text))) Texts[I]->SetText(FText::FromString(Text));
    }
}

// ------------------------------------------------------------------------------------------------------------ the reader

namespace RacingRecordsUi
{
    FLinearColor Hex(const TCHAR* InHex, float Alpha = 1.f)
    {
        FLinearColor Color = FLinearColor::FromSRGBColor(FColor::FromHex(InHex));
        Color.A = Alpha;
        return Color;
    }

    // The betting window's palette: dark forest boards, brushed brass, cream type.
    const FLinearColor BoardOuter = Hex(TEXT("0b1c15"), .96f);
    const FLinearColor BoardInner = Hex(TEXT("0e221a"), .97f);
    const FLinearColor Plaque = Hex(TEXT("102619"), 1.f);
    const FLinearColor PlaqueSelected = Hex(TEXT("1a3a2b"), 1.f);
    const FLinearColor Brass = Hex(TEXT("c9a05a"));
    const FLinearColor BrassSoft = Hex(TEXT("c9a05a"), .48f);
    const FLinearColor BrassFaint = Hex(TEXT("c9a05a"), .22f);
    const FLinearColor Gold = Hex(TEXT("e6c883"));
    const FLinearColor Cream = Hex(TEXT("fff6e5"));
    const FLinearColor Sage = Hex(TEXT("b9cbbf"));
    const FLinearColor Muted = Hex(TEXT("7f9488"));
    const FLinearColor Loss = Hex(TEXT("e08f7a"));

    const FSlateBrush* Rounded(const FLinearColor& Fill, float Radius, const FLinearColor& Outline = FLinearColor::Transparent, float Width = 0.f)
    {
        static TMap<FString, TSharedPtr<FSlateBrush>> Cache;
        const FString Key = FString::Printf(TEXT("%s:%.1f:%s:%.1f"), *Fill.ToString(), Radius, *Outline.ToString(), Width);
        if (const TSharedPtr<FSlateBrush>* Found = Cache.Find(Key)) return Found->Get();
        return Cache.Add(Key, MakeShared<FSlateRoundedBoxBrush>(FSlateColor(Fill), FVector4(Radius, Radius, Radius, Radius), FSlateColor(Outline), Width)).Get();
    }

    FSlateFontInfo Font(const char* Weight, int32 Size, int32 Spacing = 0)
    {
        FSlateFontInfo F = FCoreStyle::GetDefaultFontStyle(Weight, Size);
        F.LetterSpacing = Spacing;
        return F;
    }

    TSharedRef<STextBlock> Text(const FString& Value, const FSlateFontInfo& InFont, const FLinearColor& Color, bool bWrap = false)
    {
        return SNew(STextBlock).Text(FText::FromString(Value)).Font(InFont).ColorAndOpacity(Color).AutoWrapText(bWrap)
            .ShadowOffset(FVector2D(0.f, 1.f)).ShadowColorAndOpacity(FLinearColor(0.f, 0.f, 0.f, .6f));
    }

    struct FPadNames { const TCHAR *Accept, *Back, *Prev, *Next, *Sort, *Letter; };
    FPadNames PadNames(int32 Style)
    {
        switch (Style)
        {
            case 2: return {TEXT("Croix"), TEXT("Rond"), TEXT("L1"), TEXT("R1"), TEXT("Carré"), TEXT("Triangle")};
            case 3: return {TEXT("B"), TEXT("A"), TEXT("L"), TEXT("R"), TEXT("Y"), TEXT("X")};
            default: return {TEXT("A"), TEXT("B"), TEXT("LB"), TEXT("RB"), TEXT("X"), TEXT("Y")};
        }
    }

    /**
     * The records reader (docs/RACING.md, "Records hall"): one page of one object at a time, in the betting window's
     * forest and brass. Gamepad first: up / down choose a line, the bottom button opens its card, the right button goes
     * back, the bumpers change the ranking (a drawer, a column, a panel), left / right turn the page, the left button
     * sorts and the top button picks a first letter; on a keyboard, typing searches a name. It redraws when a page
     * arrives, never every frame.
     */
    class SRacingRecordsWindow : public SCompoundWidget
    {
    public:
        SLATE_BEGIN_ARGS(SRacingRecordsWindow) {}
        SLATE_END_ARGS()

        TWeakObjectPtr<URacingRecordsDesk> Desk;
        struct FFrame { FRacingRecordsQuery Query; int32 Selected = 0; };
        TArray<FFrame> Stack;
        bool bPad = false, bAsk = true;
        uint32 Seen = MAX_uint32, Asked = 0;
        int32 PadStyle = 0;
        float StickCooldown = 0.f, Retry = 0.f;
        bool bStickY = false;
        TSharedPtr<SBox> Body;

        void Construct(const FArguments&, URacingRecordsDesk* InDesk, const FRacingRecordsQuery& First)
        {
            Desk = InDesk;
            Stack.Add({First, 0});
            PadStyle = AJapanHUD::CurrentControllerStyle();
            bPad = PadStyle != 0;
            ChildSlot
            [
                SNew(SBox).HAlign(HAlign_Right).VAlign(VAlign_Center).Padding(FMargin(24.f, 24.f, 56.f, 24.f))
                [
                    SNew(SScaleBox).Stretch(EStretch::ScaleToFit).StretchDirection(EStretchDirection::DownOnly)
                    [
                        SNew(SBorder).BorderImage(Rounded(BoardOuter, 14.f, Brass, 1.5f)).Padding(4.f)
                        [
                            SNew(SBorder).BorderImage(Rounded(BoardInner, 11.f, BrassFaint, 1.f)).Padding(FMargin(24.f, 20.f))
                            [SAssignNew(Body, SBox).WidthOverride(600.f)]
                        ]
                    ]
                ]
            ];
            Rebuild();
        }

        FFrame& Top() { return Stack.Last(); }
        const FRacingRecordsPage* Page() const
        {
            // Only the answer to what this frame asks.
            if (!Desk.IsValid() || !Asked) return nullptr;
            const FRacingRecordsPage& P = Desk->GetPage();
            return P.Seq == Asked ? &P : nullptr;
        }
        bool IsList() const
        {
            const FRacingRecordsQuery& Q = Stack.Last().Query;
            return Q.Subject.IsEmpty() && (Q.Object == uint8(ERacingHallObject::Cabinet) || Q.Object == uint8(ERacingHallObject::Archive));
        }
        bool HasKinds() const
        {
            const FRacingRecordsQuery& Q = Stack.Last().Query;
            return Q.Subject.IsEmpty() && (Q.Object == uint8(ERacingHallObject::Cabinet) || Q.Object == uint8(ERacingHallObject::Archive) ||
                Q.Object == uint8(ERacingHallObject::Honour) || Q.Object == uint8(ERacingHallObject::Record));
        }

        void Change(TFunctionRef<void(FRacingRecordsQuery&)> Edit)
        {
            Edit(Top().Query);
            Top().Selected = 0;
            bAsk = true;
            Rebuild();
        }

        void Step(int32 Delta)
        {
            const FRacingRecordsPage* P = Page();
            if (!P || P->Lines.IsEmpty()) return;
            int32 I = Top().Selected;
            for (int32 Tries = 0; Tries < P->Lines.Num(); ++Tries)
            {
                I = (I + Delta + P->Lines.Num()) % P->Lines.Num();
                if (!P->Lines[I].bHeading) break;
            }
            Top().Selected = I;
            Rebuild();
        }
        void Turn(int32 Delta)
        {
            const FRacingRecordsPage* P = Page();
            if (!P) return;
            const int32 Next = FMath::Clamp(P->Page + Delta, 0, P->Pages - 1);
            if (Next != P->Page) Change([Next](FRacingRecordsQuery& Q) { Q.Page = Next; });
        }
        void Tab(int32 Delta)
        {
            if (!HasKinds()) return;
            Change([Delta](FRacingRecordsQuery& Q)
            {
                Q.Page = 0;
                if (Q.Object == uint8(ERacingHallObject::Record))
                    Q.Index = uint8((Q.Index + Delta + RacingRecords::Panels().Num()) % RacingRecords::Panels().Num());
                else
                {
                    // The archives keep horses and jockeys (stables are never archived).
                    const int32 Kinds = Q.Object == uint8(ERacingHallObject::Archive) ? 2 : 3;
                    Q.Kind = uint8((Q.Kind + Delta + Kinds) % Kinds);
                }
            });
        }
        void Sort()
        {
            if (!IsList()) return;
            const bool bArchive = Top().Query.Object == uint8(ERacingHallObject::Archive);
            Change([bArchive](FRacingRecordsQuery& Q) { Q.Sort = uint8((Q.Sort + 1) % (bArchive ? 2 : 3)); Q.Page = 0; });
        }
        void Letter()
        {
            if (!IsList()) return;
            Change([](FRacingRecordsQuery& Q)
            {
                const TCHAR C = Q.Search.Len() == 1 ? Q.Search[0] : TEXT('@');
                Q.Search = C >= TEXT('Z') ? FString() : FString::Chr(C < TEXT('A') ? TEXT('A') : TCHAR(C + 1));
                Q.Page = 0;
            });
        }
        void Type(const FString& Chars)
        {
            if (!IsList()) return;
            Change([&Chars](FRacingRecordsQuery& Q) { Q.Search = (Q.Search + Chars).Left(24); Q.Page = 0; });
        }
        void Accept()
        {
            const FRacingRecordsPage* P = Page();
            if (!P || !P->Lines.IsValidIndex(Top().Selected)) return;
            const FString Subject = P->Lines[Top().Selected].Subject;
            if (Subject.IsEmpty()) return;
            FRacingRecordsQuery Q = Top().Query;
            Q.Subject = Subject;
            Q.Page = 0;
            Stack.Add({Q, 0});
            bAsk = true;
            Rebuild();
        }
        /** True when there is nothing to go back to. */
        bool Back()
        {
            if (IsList() && !Top().Query.Search.IsEmpty()) { Change([](FRacingRecordsQuery& Q) { Q.Search.Reset(); Q.Page = 0; }); return false; }
            if (Stack.Num() <= 1) return true;
            Stack.Pop();
            bAsk = true;
            Rebuild();
            return false;
        }

        virtual bool SupportsKeyboardFocus() const override { return true; }
        virtual void Tick(const FGeometry& G, const double Time, const float Delta) override
        {
            SCompoundWidget::Tick(G, Time, Delta);
            StickCooldown -= Delta;
            Retry -= Delta;
            if (!Desk.IsValid()) { RacingRecords::Close(); return; }
            // A page is asked for once; the desk refuses a second ask within a tenth of a second, so retry then.
            if (bAsk && Retry <= 0.f)
            {
                if (const uint32 Seq = Desk->Ask(Top().Query)) { Asked = Seq; bAsk = false; }
                else Retry = .05f;
            }
            // A refused (busy) page is asked again a moment later.
            if (const FRacingRecordsPage* P = Page())
                if (!P->Error.IsEmpty() && P->Error.StartsWith(TEXT("Un instant")) && !bAsk) { bAsk = true; Retry = .3f; }
            if (Desk->GetRevision() != Seen) Rebuild();
            if (FSlateApplication::IsInitialized() && !HasUserFocus(0).IsSet() && !HasUserFocusedDescendants(0))
                FSlateApplication::Get().SetUserFocus(0, SharedThis(this), EFocusCause::Navigation);
        }
        virtual FReply OnPreviewKeyDown(const FGeometry&, const FKeyEvent& E) override
        {
            const FKey K = E.GetKey();
            if (K.IsGamepadKey() != bPad) { bPad = K.IsGamepadKey(); Seen = MAX_uint32; }
            const bool bTyping = IsList() && !K.IsGamepadKey();
            if (K == EKeys::Up || K == EKeys::Gamepad_DPad_Up || (!bTyping && K == EKeys::W)) Step(-1);
            else if (K == EKeys::Down || K == EKeys::Gamepad_DPad_Down || (!bTyping && K == EKeys::S)) Step(1);
            else if (K == EKeys::Left || K == EKeys::Gamepad_DPad_Left || K == EKeys::PageUp) { if (!E.IsRepeat()) Turn(-1); }
            else if (K == EKeys::Right || K == EKeys::Gamepad_DPad_Right || K == EKeys::PageDown) { if (!E.IsRepeat()) Turn(1); }
            else if (K == EKeys::Gamepad_LeftShoulder) { if (!E.IsRepeat()) Tab(-1); }
            else if (K == EKeys::Gamepad_RightShoulder || K == EKeys::Tab) { if (!E.IsRepeat()) Tab(1); }
            else if (K == EKeys::Gamepad_FaceButton_Left || (!bTyping && K == EKeys::F) || K == EKeys::F2) { if (!E.IsRepeat()) Sort(); }
            else if (K == EKeys::Gamepad_FaceButton_Top) { if (!E.IsRepeat()) Letter(); }
            else if (K == EKeys::Enter || K == EKeys::SpaceBar || K == EKeys::Gamepad_FaceButton_Bottom || K == EKeys::Virtual_Gamepad_Accept.GetVirtualKey())
            {
                if (!E.IsRepeat()) Accept();
            }
            else if (K == EKeys::BackSpace && bTyping && !Top().Query.Search.IsEmpty())
                Change([](FRacingRecordsQuery& Q) { Q.Search.LeftChopInline(1); Q.Page = 0; });
            else if (K == EKeys::Escape || K == EKeys::BackSpace || K == EKeys::Gamepad_FaceButton_Right || K == EKeys::Virtual_Gamepad_Back.GetVirtualKey() ||
                K == EKeys::Gamepad_Special_Right || K == EKeys::Gamepad_Special_Left)
            {
                if (!E.IsRepeat() && (Back() || K == EKeys::Gamepad_Special_Right || K == EKeys::Gamepad_Special_Left)) RacingRecords::Close();
            }
            else if (bTyping) return FReply::Unhandled();   // a letter: OnKeyChar searches with it
            return FReply::Handled();
        }
        virtual FReply OnKeyChar(const FGeometry&, const FCharacterEvent& E) override
        {
            const TCHAR C = E.GetCharacter();
            if (IsList() && (FChar::IsAlnum(C) || C == TEXT(' ') || C == TEXT('-') || C == TEXT('\'') || C >= 0xC0)) Type(FString::Chr(C));
            return FReply::Handled();
        }
        virtual FReply OnKeyDown(const FGeometry&, const FKeyEvent&) override { return FReply::Handled(); }
        virtual FReply OnKeyUp(const FGeometry&, const FKeyEvent&) override { return FReply::Handled(); }
        virtual FReply OnAnalogValueChanged(const FGeometry&, const FAnalogInputEvent& E) override
        {
            if (E.GetKey() != EKeys::Gamepad_LeftY) return FReply::Unhandled();
            const float V = E.GetAnalogValue();
            if (FMath::Abs(V) < .3f) { bStickY = false; return FReply::Handled(); }
            if (FMath::Abs(V) > .6f && (!bStickY || StickCooldown <= 0.f))
            {
                bStickY = true;
                StickCooldown = .22f;
                Step(V > 0.f ? -1 : 1);
            }
            return FReply::Handled();
        }

        // ------------------------------------------------------------ drawing
        void Rebuild()
        {
            if (!Body.IsValid()) return;
            Seen = Desk.IsValid() ? Desk->GetRevision() : 0;
            if (const FRacingRecordsPage* P = Page())
            {
                int32& Sel = Top().Selected;
                Sel = P->Lines.IsEmpty() ? 0 : FMath::Clamp(Sel, 0, P->Lines.Num() - 1);
                // Never rest on a heading.
                for (int32 I = 0; I < P->Lines.Num() && P->Lines.IsValidIndex(Sel) && P->Lines[Sel].bHeading; ++I) Sel = (Sel + 1) % P->Lines.Num();
            }
            Body->SetContent(Build());
        }

        TSharedRef<SWidget> Build()
        {
            const FRacingRecordsPage* P = Page();
            const FRacingRecordsQuery& Q = Stack.Last().Query;
            TSharedRef<SVerticalBox> Root = SNew(SVerticalBox);
            Root->AddSlot().AutoHeight()[Text(P ? P->Kicker : FString(TEXT("SALLE DES COURSES")), Font("Bold", 10, 200), Gold)];
            Root->AddSlot().AutoHeight().Padding(0.f, 2.f, 0.f, 0.f)[Text(P && P->Error.IsEmpty() ? P->Title : FString(TEXT("…")), Font("Bold", 22), Cream)];
            if (P && !P->Intro.IsEmpty()) Root->AddSlot().AutoHeight().Padding(0.f, 6.f, 0.f, 0.f)[Text(P->Intro, Font("Regular", 12), Sage, true)];
            // The ranking's tabs.
            if (HasKinds() && Q.Object != uint8(ERacingHallObject::Record))
            {
                TSharedRef<SHorizontalBox> Tabs = SNew(SHorizontalBox);
                const int32 Kinds = Q.Object == uint8(ERacingHallObject::Archive) ? 2 : 3;
                for (int32 K = 0; K < Kinds; ++K)
                {
                    const bool bOn = K == Q.Kind;
                    Tabs->AddSlot().AutoWidth().Padding(0.f, 0.f, 6.f, 0.f)
                    [
                        SNew(SBorder).BorderImage(Rounded(bOn ? PlaqueSelected : Plaque, 7.f, bOn ? Brass : BrassFaint, 1.f)).Padding(FMargin(10.f, 3.f))
                        [Text(RacingRecordsText::KindName(ERacingHallKind(K)), Font("Bold", 11), bOn ? Cream : Muted)]
                    ];
                }
                if (IsList())
                    Tabs->AddSlot().FillWidth(1.f).HAlign(HAlign_Right).VAlign(VAlign_Center)
                    [Text(Q.Search.IsEmpty() ? FString(TEXT("Recherche : tapez un nom")) : FString::Printf(TEXT("Recherche : %s_"), *Q.Search), Font("Regular", 11), Q.Search.IsEmpty() ? Muted : Gold)];
                Root->AddSlot().AutoHeight().Padding(0.f, 10.f, 0.f, 0.f)[Tabs];
            }
            Root->AddSlot().AutoHeight().Padding(0.f, 10.f, 0.f, 10.f)[SNew(SBox).HeightOverride(1.f)[SNew(SImage).Image(Rounded(BrassSoft, 0.f))]];
            if (!P) Root->AddSlot().AutoHeight()[Text(TEXT("Le greffier cherche la page…"), Font("Regular", 13), Muted)];
            else if (!P->Error.IsEmpty()) Root->AddSlot().AutoHeight()[Text(P->Error, Font("Bold", 13), Loss, true)];
            else
            {
                if (P->Lines.IsEmpty()) Root->AddSlot().AutoHeight()[Text(TEXT("Rien d'inscrit ici pour le moment."), Font("Regular", 13), Muted)];
                for (int32 I = 0; I < P->Lines.Num(); ++I)
                {
                    const FRacingRecordsLine& L = P->Lines[I];
                    if (L.bHeading)
                    {
                        Root->AddSlot().AutoHeight().Padding(2.f, I ? 8.f : 0.f, 0.f, 4.f)[Text(RacingRecordsText::Upper(L.Left), Font("Bold", 10, 150), Gold)];
                        continue;
                    }
                    const bool bSel = I == Top().Selected;
                    TWeakPtr<SRacingRecordsWindow> Self = SharedThis(this);
                    Root->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 4.f)
                    [
                        SNew(SButton).ButtonStyle(&FCoreStyle::Get().GetWidgetStyle<FButtonStyle>("NoBorder")).ContentPadding(0)
                        .OnClicked_Lambda([Self, I] { if (auto W = Self.Pin()) { if (W->Top().Selected == I) W->Accept(); else { W->Top().Selected = I; W->Rebuild(); } } return FReply::Handled(); })
                        [
                            SNew(SBorder).BorderImage(Rounded(bSel ? PlaqueSelected : Plaque, 8.f, bSel ? Brass : BrassFaint, bSel ? 1.5f : 1.f)).Padding(FMargin(12.f, 6.f))
                            [
                                SNew(SHorizontalBox)
                                + SHorizontalBox::Slot().FillWidth(1.f)
                                [
                                    SNew(SVerticalBox)
                                    + SVerticalBox::Slot().AutoHeight()[Text(L.Left, Font("Bold", 14), bSel ? Cream : Sage)]
                                    + SVerticalBox::Slot().AutoHeight()[Text(L.Sub, Font("Regular", 11), Muted, true)]
                                ]
                                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(10.f, 0.f, 0.f, 0.f)
                                [Text(L.Right, Font("Bold", 14), bSel ? Gold : BrassSoft)]
                            ]
                        ]
                    ];
                }
                if (P->Pages > 1)
                    Root->AddSlot().AutoHeight().Padding(2.f, 4.f, 0.f, 0.f)[Text(FString::Printf(TEXT("Page %d / %d"), P->Page + 1, P->Pages), Font("Bold", 11), BrassSoft)];
            }
            const FPadNames Pad = PadNames(PadStyle == 0 ? 1 : PadStyle);
            const bool bCard = P && P->Lines.IsValidIndex(Top().Selected) && !P->Lines[Top().Selected].Subject.IsEmpty();
            TArray<FString> Legend;
            Legend.Add(bPad ? TEXT("Haut / Bas  Choisir") : TEXT("↑ / ↓  Choisir"));
            if (bCard) Legend.Add(FString::Printf(TEXT("%s  Lire la fiche"), bPad ? Pad.Accept : TEXT("Entrée")));
            if (P && P->Pages > 1) Legend.Add(bPad ? TEXT("Gauche / Droite  Page") : TEXT("← / →  Page"));
            if (HasKinds())
                Legend.Add(FString::Printf(TEXT("%s  %s"), bPad ? *FString::Printf(TEXT("%s / %s"), Pad.Prev, Pad.Next) : TEXT("Tab"),
                    Q.Object == uint8(ERacingHallObject::Record) ? TEXT("Autre registre")
                    : Q.Object == uint8(ERacingHallObject::Archive) ? TEXT("Chevaux / Jockeys") : TEXT("Chevaux / Jockeys / Écuries")));
            if (IsList())
            {
                Legend.Add(FString::Printf(TEXT("%s  Trier"), bPad ? Pad.Sort : TEXT("F2")));
                if (bPad) Legend.Add(FString::Printf(TEXT("%s  Première lettre"), Pad.Letter));
            }
            Legend.Add(FString::Printf(TEXT("%s  %s"), bPad ? Pad.Back : TEXT("Échap"), Stack.Num() > 1 || (IsList() && !Q.Search.IsEmpty()) ? TEXT("Retour") : TEXT("Fermer")));
            Root->AddSlot().AutoHeight().Padding(0.f, 12.f, 0.f, 0.f)[Text(FString::Join(Legend, TEXT("   ·   ")), Font("Regular", 11), Hex(TEXT("f3e8d2")), true)];
            return Root;
        }

        FString Json() const
        {
            const FRacingRecordsQuery& Q = Stack.Last().Query;
            const FRacingRecordsPage* P = Page();
            FString Lines;
            if (P)
                for (const FRacingRecordsLine& L : P->Lines)
                    Lines += FString::Printf(TEXT("%s{\"left\":\"%s\",\"right\":\"%s\",\"sub\":\"%s\",\"subject\":\"%s\",\"heading\":%s}"), Lines.IsEmpty() ? TEXT("") : TEXT(","),
                        *RacingJsonEscape(L.Left), *RacingJsonEscape(L.Right), *RacingJsonEscape(L.Sub), *RacingJsonEscape(L.Subject), L.bHeading ? TEXT("true") : TEXT("false"));
            return FString::Printf(TEXT("{\"object\":%d,\"index\":%d,\"kind\":%d,\"sort\":%d,\"search\":\"%s\",\"subject\":\"%s\",\"depth\":%d,\"selected\":%d,"
                "\"page\":%d,\"pages\":%d,\"kicker\":\"%s\",\"title\":\"%s\",\"intro\":\"%s\",\"error\":\"%s\",\"lines\":[%s]}"),
                Q.Object, Q.Index, Q.Kind, Q.Sort, *RacingJsonEscape(Q.Search), *RacingJsonEscape(Q.Subject), Stack.Num(), Stack.Last().Selected,
                P ? P->Page : -1, P ? P->Pages : 0, P ? *RacingJsonEscape(P->Kicker) : TEXT(""), P ? *RacingJsonEscape(P->Title) : TEXT(""),
                P ? *RacingJsonEscape(P->Intro) : TEXT(""), P ? *RacingJsonEscape(P->Error) : TEXT(""), *Lines);
        }
    };

    struct FOpen
    {
        TSharedPtr<SRacingRecordsWindow> Window;
        TWeakObjectPtr<AWandererCharacter> Player;
    };
    FOpen& Open()
    {
        static FOpen State;
        return State;
    }

    int32 InReach(const AWandererCharacter* Pawn, const ARacingRecordsHall*& OutHall)
    {
        OutHall = nullptr;
        if (!Pawn || !Pawn->IsLocallyControlled() || !Pawn->IsReady() || Pawn->IsMenuOpen() || RacingRecords::IsOpen() || RacingStables::IsOpen() ||
            RacingCounter::IsOpen() || Pawn->OnVehicle() || Pawn->IsZeppelinPassenger() || (Pawn->GetSkate() && Pawn->GetSkate()->IsRiding()))
            return INDEX_NONE;
        OutHall = ARacingRecordsHall::Find(Pawn);
        if (!OutHall || !OutHall->NumShown() || !URacingRecordsDesk::Of(Pawn->GetController())) return INDEX_NONE;
        // Where the player looks: the camera's yaw (the pawn may stand sideways).
        const AController* C = Pawn->GetController();
        const FVector Facing = C ? FRotator(0., C->GetControlRotation().Yaw, 0.).Vector() : Pawn->GetActorForwardVector();
        return RacingRecords::AnchorInReach(OutHall->GetAnchors(), Pawn->GetActorLocation(), Facing);
    }
}

FString RacingRecords::Prompt(const AWandererCharacter* Pawn)
{
    const ARacingRecordsHall* Hall = nullptr;
    const int32 I = RacingRecordsUi::InReach(Pawn, Hall);
    if (I == INDEX_NONE) return FString();
    const FAnchor& A = Hall->GetAnchors()[I];
    switch (A.Object)
    {
        case ERacingHallObject::Board: return TEXT("Lire le tableau des courses");
        case ERacingHallObject::Record: return FString::Printf(TEXT("Records : %s"), Panels().IsValidIndex(A.Index) ? *Panels()[A.Index].Name : TEXT(""));
        case ERacingHallObject::Honour:
        {
            // "Les plus de Grands Prix" -> "les plus de Grands Prix": only its first letter lowered.
            FString Name = HonourName(ERacingHonour(A.Index));
            Name[0] = FChar::ToLower(Name[0]);
            return FString::Printf(TEXT("Tableau d'honneur : %s"), *Name);
        }
        case ERacingHallObject::Cabinet: return TEXT("Ouvrir le fichier");
        case ERacingHallObject::Archive: return TEXT("Consulter les archives");
        default: return TEXT("Lire : salle des courses");
    }
}

bool RacingRecords::TryOpen(AWandererCharacter* Pawn)
{
    using namespace RacingRecordsUi;
    const ARacingRecordsHall* Hall = nullptr;
    const int32 I = InReach(Pawn, Hall);
    if (I == INDEX_NONE || !GEngine || !GEngine->GameViewport) return false;
    URacingRecordsDesk* Desk = URacingRecordsDesk::Of(Pawn->GetController());
    const FAnchor& A = Hall->GetAnchors()[I];
    FOpen& State = Open();
    Desk->SetInHall(true);
    State.Window = SNew(SRacingRecordsWindow, Desk, FirstQuery(A));
    State.Player = Pawn;
    GEngine->GameViewport->AddViewportWidgetContent(State.Window.ToSharedRef(), 22);
    Pawn->SetMenuOpen(true);
    FSlateApplication::Get().SetUserFocus(0, State.Window, EFocusCause::SetDirectly);
    UE_LOG(LogTemp, Display, TEXT("RACING RECORDS reader open (object %d, index %d)"), int32(A.Object), A.Index);
    return true;
}

bool RacingRecords::IsOpen()
{
    return RacingRecordsUi::Open().Window.IsValid();
}

void RacingRecords::Close()
{
    RacingRecordsUi::FOpen& State = RacingRecordsUi::Open();
    if (!State.Window.IsValid()) return;
    if (GEngine && GEngine->GameViewport) GEngine->GameViewport->RemoveViewportWidgetContent(State.Window.ToSharedRef());
    State.Window.Reset();
    if (AWandererCharacter* Pawn = State.Player.Get()) Pawn->SetMenuOpen(false);
    State.Player.Reset();
    UE_LOG(LogTemp, Display, TEXT("RACING RECORDS reader closed"));
}

FString RacingRecords::WindowJson()
{
    const RacingRecordsUi::FOpen& State = RacingRecordsUi::Open();
    return State.Window.IsValid() ? State.Window->Json() : FString(TEXT("null"));
}

bool RacingRecords::Press(const FString& Key)
{
    RacingRecordsUi::FOpen& State = RacingRecordsUi::Open();
    if (!State.Window.IsValid()) return false;
    RacingRecordsUi::SRacingRecordsWindow& W = *State.Window;
    if (Key == TEXT("up")) W.Step(-1);
    else if (Key == TEXT("down")) W.Step(1);
    else if (Key == TEXT("accept")) W.Accept();
    else if (Key == TEXT("back")) { if (W.Back()) Close(); }
    else if (Key == TEXT("next")) W.Turn(1);
    else if (Key == TEXT("prev")) W.Turn(-1);
    else if (Key == TEXT("kind")) W.Tab(1);
    else if (Key == TEXT("sort")) W.Sort();
    else if (Key == TEXT("letter")) W.Letter();
    else if (Key.StartsWith(TEXT("type:"))) W.Type(Key.Mid(5));
    else return false;
    return true;
}

bool RacingRecords::GoTo(AWandererCharacter* Pawn, const FString& Spot)
{
    FVector Origin, Centre;
    TArray<FAnchor> Anchors;
    if (!Pawn || !RacingCounter::RegionOrigin(Pawn, Origin) || !HallAnchors(RacingPlaces::Belmonte(), Origin, Anchors, Centre)) return false;
    const FString Name = Spot.TrimStartAndEnd().ToLower();
    ERacingHallObject Object = ERacingHallObject::Board;
    int32 Index = 0;
    if (Name.StartsWith(TEXT("record"))) { Object = ERacingHallObject::Record; Index = FCString::Atoi(*Name.Mid(6).TrimStartAndEnd()); }
    else if (Name.StartsWith(TEXT("honour")) || Name.StartsWith(TEXT("honor"))) { Object = ERacingHallObject::Honour; Index = FCString::Atoi(*Name.Mid(6).TrimStartAndEnd()); }
    else if (Name.StartsWith(TEXT("cabinet"))) Object = ERacingHallObject::Cabinet;
    else if (Name.StartsWith(TEXT("archive"))) Object = ERacingHallObject::Archive;
    else if (Name.StartsWith(TEXT("plaque"))) Object = ERacingHallObject::Plaque;
    const FAnchor* A = Anchors.FindByPredicate([&](const FAnchor& X) { return X.Object == Object && X.Index == Index; });
    if (!A) return false;
    // In front of it, facing it, on the loggia's floor (further from the high split-flap board).
    const FVector Stand = A->At.TransformPosition(FVector(A->Object == ERacingHallObject::Board ? 300. : 140., 0., 0.));
    return Pawn->TravelTo(FVector(Stand.X, Stand.Y, A->Floor + 95.), A->At.Rotator().Yaw + 180.f, TEXT("records hall"), 150.f);
}

static FAutoConsoleCommandWithWorldAndArgs RacingRecordsCommand(TEXT("racing.Records"),
    TEXT("racing.Records board|record <n>|honour <n>|cabinet|archive|plaque: stand before an object of the records hall"),
    FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
    {
        APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
        RacingRecords::GoTo(PC ? Cast<AWandererCharacter>(PC->GetPawn()) : nullptr, FString::Join(Args, TEXT(" ")));
    }));

// ------------------------------------------------------------------------------------------------------------ live

FString URacingRecordsLive::RacingRecords()
{
    UWorld* World = ULiveLibrary::GameWorld();
    const URacingRecordsDesk* Desk = URacingRecordsDesk::Local(World);
    const ARacingRecordsHall* Hall = ARacingRecordsHall::Find(World);
    const ARacingService* Service = ARacingService::Find(World);
    const AWandererCharacter* Pawn = Cast<AWandererCharacter>(ULiveLibrary::Player());
    auto E = [](const FString& T) { return RacingJsonEscape(T); };
    FString Records, Honours;
    if (Desk)
    {
        for (const FString& R : Desk->GetBoards().Records) Records += (Records.IsEmpty() ? TEXT("\"") : TEXT(",\"")) + E(R) + TEXT("\"");
        for (const FString& H : Desk->GetBoards().Honours) Honours += (Honours.IsEmpty() ? TEXT("\"") : TEXT(",\"")) + E(H) + TEXT("\"");
    }
    int32 Reach = INDEX_NONE;
    if (Hall && Pawn) Reach = RacingRecords::AnchorInReach(Hall->GetAnchors(), Pawn->GetActorLocation(),
        Pawn->GetController() ? FRotator(0., Pawn->GetController()->GetControlRotation().Yaw, 0.).Vector() : Pawn->GetActorForwardVector());
    const FRacingLedger* Ledger = Service && Service->HasAuthority() ? &Service->GetLedger() : nullptr;
    return FString::Printf(TEXT("{\"ledger\":{\"since\":%d,\"records\":%d,\"riders\":%d},\"shown\":%d,\"anchors\":%d,\"reach\":%d,\"prompt\":\"%s\","
        "\"boards\":{\"day\":%d,\"standings\":\"%s\",\"upcoming\":\"%s\",\"records\":[%s],\"honours\":[%s],\"cabinet\":\"%s\",\"archive\":\"%s\"},\"window\":%s}"),
        Ledger ? Ledger->SinceT : -1, Ledger ? Ledger->Records.Num() : -1, Ledger ? Ledger->Riders.Num() : -1, Hall ? Hall->NumShown() : 0,
        Hall ? Hall->GetAnchors().Num() : 0, Reach, *E(RacingRecords::Prompt(Pawn)), Desk ? Desk->GetBoards().Day : -1,
        Desk ? *E(Desk->GetBoards().Standings) : TEXT(""), Desk ? *E(Desk->GetBoards().Upcoming) : TEXT(""), *Records, *Honours,
        Desk ? *E(Desk->GetBoards().Cabinet) : TEXT(""), Desk ? *E(Desk->GetBoards().Archive) : TEXT(""), *RacingRecords::WindowJson());
}

bool URacingRecordsLive::RacingRecordsGo(const FString& Spot)
{
    return RacingRecords::GoTo(Cast<AWandererCharacter>(ULiveLibrary::Player()), Spot);
}

bool URacingRecordsLive::RacingRecordsOpen()
{
    return RacingRecords::TryOpen(Cast<AWandererCharacter>(ULiveLibrary::Player()));
}

bool URacingRecordsLive::RacingRecordsPress(const FString& Key)
{
    return RacingRecords::Press(Key);
}
