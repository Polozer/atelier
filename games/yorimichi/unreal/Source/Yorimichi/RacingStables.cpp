#include "RacingStables.h"
#include "HidamariStable.h"
#include "RacingPlaces.h"
#include "Dom/JsonObject.h"
#include "RacingIdentity.h"
#include "AtelierData.h"
#include "HRClock.h"
#include "HRContent.h"
#include "HRRules.h"
#include "HRSave.h"
#include "JapanHUD.h"
#include "LiveLibrary.h"
#include "RacingBetting.h"
#include "RacingService.h"
#include "SkateComponent.h"
#include "WandererCharacter.h"
#include "Brushes/SlateColorBrush.h"
#include "Brushes/SlateRoundedBoxBrush.h"
#include "Components/StaticMeshComponent.h"
#include "Components/TextRenderComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Misc/FileHelper.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "Input/Events.h"
#include "InputCoreTypes.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Net/UnrealNetwork.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Styling/CoreStyle.h"
#include "UObject/ConstructorHelpers.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

// ------------------------------------------------------------------------------------------------------------ sites

const TArray<RacingStables::FSiteDef>& RacingStables::Sites()
{
    // Paul's: the existing Belmonte estate signed "Votre écurie" (Haras Valley's estate 0, Val d'Oro, the rules' stable for
    // sale "old_mill", whose colour it already wears). Henry's: the new Hidamari stable (world/regions/hidamari_stable).
    static const TArray<FSiteDef> List = {
        {TEXT("belmonte"), TEXT("old_mill"), TEXT("Écurie de la Vallée"), nullptr, EClaim::HostPlayer, TEXT("Belmonte")},
        {TEXT("hidamari"), TEXT("hidamari"), TEXT("Écurie Hidamari"), TEXT("c8553d"), EClaim::AnyPlayer, TEXT("Hidamari")},
    };
    return List;
}

int32 RacingStables::SiteIndexOfStable(const FString& StableId)
{
    return Sites().IndexOfByPredicate([&StableId](const FSiteDef& S) { return StableId == S.StableId; });
}

bool RacingStables::RenameStable(FHRWorldState& S, const FString& From, const FString& To)
{
    if (From == To || !HRRules::FindStable(S, From) || HRRules::FindStable(S, To)) return false;
    auto Swap = [&](FString& Id) { if (Id == From) Id = To; };
    for (FHRStable& St : S.Stables) Swap(St.Id);
    for (TPair<FString, FHRHorse>& It : S.Horses)
    {
        Swap(It.Value.OwnerId);
        for (FString& O : It.Value.Owners) Swap(O);
        for (FHRCareerLine& L : It.Value.Career) Swap(L.StableId);
    }
    for (TPair<FString, FHRRider>& It : S.Riders)
    {
        Swap(It.Value.OwnerId);
        for (FString& O : It.Value.Stables) Swap(O);
    }
    for (FHRNews& N : S.News) for (FString& Id : N.StableIds) Swap(Id);
    for (FHRSaleListing& L : S.Listings) Swap(L.SellerId);
    for (FHRPregnancy& P : S.Pregnancies) Swap(P.BreederId);
    for (FHRRace& R : S.Meeting.Races)
    {
        for (FHRRunner& E : R.Entries) Swap(E.StableId);
        for (FHRFinish& F : R.Finishes) Swap(F.StableId);
        for (FHRRaceRun& Run : R.Runs) for (FHRFinish& F : Run.Finishes) Swap(F.StableId);
    }
    return true;
}

FString RacingStables::Assign(FHRWorldState& S, const FString& PlayerId)
{
    if (!HRRules::FindPlayer(S, PlayerId)) return TEXT("Pas de portefeuille pour ce joueur.");
    if (HRRules::PlayerStable(S, PlayerId)) return FString();
    // A session player (a guest without a usable install id, RacingIdentity) is not kept beyond the session: no stable,
    // so Hidamari waits for the first guest who will come back.
    if (!RacingIdentity::IsPersistent(PlayerId)) return TEXT("Une écurie est réservée aux joueurs reconnus d'une session à l'autre.");
    const bool bHost = RacingIdentity::IsHost(PlayerId);
    for (const FSiteDef& Site : Sites())
    {
        if (Site.Claim == EClaim::HostPlayer && !bHost) continue;
        FHRStable* St = HRRules::FindStable(S, Site.StableId);
        if (St && St->IsPlayerOwned()) continue;
        // V1 players get their stable free: the rules' price is lent for the purchase and the balance restored after it.
        const int32 Before = HRRules::FindPlayer(S, PlayerId)->Coins;
        FString Why;
        if (St && St->bForSale)
        {
            HRRules::FindPlayer(S, PlayerId)->Coins = Before + HRRules::StablePrice;
            Why = HRRules::BuyStable(S, PlayerId, Site.StableId, true);
        }
        else if (St)
        {
            // A site stable no one owns (a guest's that went back to the world): taken over as it is, its money left behind.
            St->OwnerPlayerId = PlayerId;
            St->Coins = 0;
            St->Debt = 0;
            St->Profile = TEXT("player");
        }
        else
        {
            // Founded by the site itself ("site:<id>", a stand-in player for the call only), so nothing the stable keeps
            // (its starter horse's id) carries the first owner's id, a guest's session id least of all.
            const FString Founder = FString(TEXT("site:")) + Site.Id;
            const FString Name = HRRules::FindPlayer(S, PlayerId)->Name;
            HRRules::AddPlayer(S, Founder, Name).Coins = HRRules::StablePrice;
            Why = HRRules::FoundStable(S, Founder, Site.Name ? Site.Name : TEXT(""), Site.Color ? Site.Color : TEXT(""));
            S.Players.Remove(Founder);
            if (Why.IsEmpty())
            {
                RenameStable(S, TEXT("player:") + Founder, Site.StableId);
                HRRules::FindStable(S, Site.StableId)->OwnerPlayerId = PlayerId;
            }
        }
        HRRules::FindPlayer(S, PlayerId)->Coins = Before;
        if (!Why.IsEmpty()) return French(Why);
        FHRStable* Mine = HRRules::PlayerStable(S, PlayerId);
        if (!Mine) return TEXT("L'écurie n'a pas pu être attribuée.");
        if (Site.Name) Mine->Name = Site.Name;
        if (Site.Color) Mine->Color = Site.Color;
        // Its three jockeys ride the stable's runners (riding them oneself comes later).
        HRRules::SetPlayerRides(S, PlayerId, false);
        if (HRRules::StableRiders(S, Mine->Id).Num() < HRRules::RidersPerStable) HRRules::SignAcademyRiders(S, Mine->Id);
        return FString();
    }
    return TEXT("Toutes les écuries des joueurs sont prises.");
}

void RacingStables::Release(FHRWorldState& S, const FString& PlayerId)
{
    FHRStable* St = HRRules::PlayerStable(S, PlayerId);
    if (!St) return;
    St->OwnerPlayerId.Reset();
    St->Coins = 0;
    St->Debt = 0;
    for (FHRRace& R : S.Meeting.Races)
        for (FHRRunner& E : R.Entries)
            if (E.RiderPlayerId == PlayerId) E.RiderPlayerId.Reset();
}

void RacingStables::ReleaseSessionStables(FHRWorldState& S)
{
    TArray<FString> Owners;
    for (const FHRStable& St : S.Stables)
        if (ARacingService::IsSessionPlayer(St.OwnerPlayerId)) Owners.Add(St.OwnerPlayerId);
    for (const FString& Id : Owners) Release(S, Id);
    for (FHRRace& R : S.Meeting.Races)
        for (FHRRunner& E : R.Entries)
            if (ARacingService::IsSessionPlayer(E.RiderPlayerId)) E.RiderPlayerId.Reset();
}

// ------------------------------------------------------------------------------------------------------------ requests

namespace RacingStableRules
{
    int32 FirstNumber(const FString& Text)
    {
        for (int32 I = 0; I < Text.Len(); ++I)
            if (FChar::IsDigit(Text[I])) return FCString::Atoi(*Text.Mid(I));
        return 0;
    }

    FString AgeLabel(int32 BirthT, int32 T)
    {
        const int32 Months = FMath::Max(0, HRClock::LifeMonths(BirthT, T));
        const int32 Years = Months / 12, Rest = Months % 12;
        if (Years == 0) return FString::Printf(TEXT("%d mois"), Rest);
        return Rest ? FString::Printf(TEXT("%d an%s %d mois"), Years, Years > 1 ? TEXT("s") : TEXT(""), Rest)
                    : FString::Printf(TEXT("%d an%s"), Years, Years > 1 ? TEXT("s") : TEXT(""));
    }

    TArray<uint8> Abilities(const FHRHorse& H)
    {
        TArray<uint8> Out;
        for (int32 I = 0; I < 4; ++I) Out.Add(uint8(FMath::Clamp(H.Abilities.IsValidIndex(I) ? H.Abilities[I] : 0, 0, 255)));
        return Out;
    }

    const FHRSaleListing* Listing(const FHRWorldState& S, const FString& HorseId)
    {
        return S.Listings.FindByPredicate([&HorseId](const FHRSaleListing& L) { return L.HorseId == HorseId; });
    }

    FString StableName(const FHRWorldState& S, const FString& Id)
    {
        const FHRStable* St = HRRules::FindStable(S, Id);
        return St ? St->Name : Id;
    }

    FRacingStableRider Rider(const FHRWorldState& S, const FHRRider& R)
    {
        FRacingStableRider Out;
        Out.Id = R.Id;
        Out.Name = R.FullName();
        Out.Country = R.Country;
        Out.Stable = R.OwnerId.IsEmpty() ? FString() : StableName(S, R.OwnerId);
        Out.Legend = R.Legend.IsEmpty() ? FString() : HRRules::LegendTitle(R.Legend);
        for (int32 I = 0; I < 4; ++I) Out.Stats.Add(uint8(HRRules::RiderStat(R.Skill.IsValidIndex(I) ? R.Skill[I] : 0)));
        Out.Overall = HRRules::RiderOverall(R);
        Out.Age = HRRules::RiderAgeMonths(R, S.T) / 12;
        Out.Wage = R.Wage;
        Out.Price = R.ListedPrice;
        Out.bListed = R.ListedPrice > 0;
        Out.Rides = R.Rides;
        Out.Wins = R.Wins;
        return Out;
    }

    FRacingStableOffer Offer(const FHRWorldState& S, const FHRHorse& H, const FString& Key, int32 Price, const FString& Seller)
    {
        FRacingStableOffer Out;
        Out.Key = Key;
        Out.Name = H.Name;
        Out.Seller = Seller;
        Out.Age = AgeLabel(H.BirthT, S.T);
        Out.bMare = H.bMare;
        Out.Abilities = Abilities(H);
        Out.Score = HRRules::CardScore(H);
        Out.Price = Price;
        Out.Wins = H.Wins;
        return Out;
    }

    FString HorseRefusal(const FHRWorldState& S, const FString& PlayerId, const FString& HorseId)
    {
        const FHRStable* St = HRRules::PlayerStable(S, PlayerId);
        const FHRHorse* H = S.Horses.Find(HorseId);
        if (!St) return TEXT("Vous n'avez pas encore d'écurie.");
        if (!H || H->OwnerId != St->Id) return TEXT("Ce cheval n'est pas à vous.");
        return FString();
    }

    /** Why a horse of the stable cannot be entered now ("" when it can). */
    FString EntryRefusal(const FHRWorldState& S, const FHRHorse& H)
    {
        if (H.IsRetired()) return TEXT("Il a pris sa retraite.");
        if (H.Injury.bActive) return TEXT("Il est blessé : repos complet.");
        if (S.T < H.ReadyT) return FString::Printf(TEXT("Trop jeune : il pourra courir le jour %d."), H.ReadyT);
        if (S.T >= H.ScheduledRetirementT) return TEXT("Sa carrière de course est finie.");
        if (H.Placement != TEXT("active")) return TEXT("Il est au pré : six chevaux au plus à l'entraînement.");
        return FString();
    }
}

FString RacingStables::French(const FString& Refusal)
{
    if (Refusal.IsEmpty()) return Refusal;
    const int32 N = RacingStableRules::FirstNumber(Refusal);
    // A breeding refusal about one horse: "<name>: <reason>".
    FString Who, Why = Refusal;
    if (!Refusal.StartsWith(TEXT("A stable keeps")) && Refusal.Split(TEXT(": "), &Who, &Why) && Who.Len() < 64 && !Who.Contains(TEXT(" coins")))
    {
        const FString Said = French(Why);
        if (Said != Why) return Who + TEXT(" : ") + Said.Left(1).ToLower() + Said.Mid(1);
    }
    struct FLine { const TCHAR* English; const TCHAR* Said; bool bNumber; };
    static const FLine Lines[] = {
        {TEXT("Unknown player"), TEXT("Pas de portefeuille pour ce joueur."), false},
        {TEXT("Buy a stable first"), TEXT("Vous n'avez pas encore d'écurie."), false},
        {TEXT("You already own a stable"), TEXT("Vous avez déjà une écurie."), false},
        {TEXT("This stable is not for sale"), TEXT("Cette écurie n'est pas à vendre."), false},
        {TEXT("This stable already exists"), TEXT("Cette écurie existe déjà."), false},
        {TEXT("This horse is already sold"), TEXT("Ce cheval est déjà vendu."), false},
        {TEXT("This horse is no longer for sale"), TEXT("Ce cheval n'est plus à vendre."), false},
        {TEXT("This horse is already yours"), TEXT("Ce cheval est déjà à vous."), false},
        {TEXT("This horse is not yours"), TEXT("Ce cheval n'est pas à vous."), false},
        {TEXT("A retired or injured horse cannot be sold"), TEXT("Un cheval retraité ou blessé ne se vend pas."), false},
        {TEXT("This rider is no longer available"), TEXT("Ce jockey n'est plus disponible."), false},
        {TEXT("This rider already rides for you"), TEXT("Ce jockey monte déjà pour vous."), false},
        {TEXT("A stable keeps"), TEXT("Une écurie garde {n} jockeys : libérez-en un d'abord."), true},
        {TEXT("This rider is not on the transfer list"), TEXT("Ce jockey n'est pas sur la liste des transferts."), false},
        {TEXT("This rider does not ride for you"), TEXT("Ce jockey ne monte pas pour vous."), false},
        {TEXT("Choose one of your horses first"), TEXT("Choisissez d'abord un de vos chevaux."), false},
        {TEXT("It takes a mare and a stallion"), TEXT("Il faut une jument et un étalon."), false},
        {TEXT("These two horses are too closely related"), TEXT("Ces deux chevaux sont trop proches parents."), false},
        {TEXT("One covering a day"), TEXT("Une saillie par jour : la prochaine demain."), false},
        {TEXT("Horse not found"), TEXT("Ce cheval est introuvable."), false},
        {TEXT("The covering could not take place"), TEXT("La saillie n'a pas pu avoir lieu."), false},
        {TEXT("Not available for breeding"), TEXT("Pas disponible pour la reproduction."), false},
        {TEXT("Too young: two horse years"), TEXT("Trop jeune : deux ans au moins."), false},
        {TEXT("Not grown yet"), TEXT("Pas encore adulte."), false},
        {TEXT("Injured: in care"), TEXT("Blessé : en soins."), false},
        {TEXT("Already in foal"), TEXT("Déjà pleine."), false},
        {TEXT("Its breeding career is over"), TEXT("Sa carrière au haras est finie."), false},
    };
    for (const FLine& L : Lines)
        if (Refusal.StartsWith(L.English)) return L.bNumber ? FString(L.Said).Replace(TEXT("{n}"), *FString::FromInt(N)) : FString(L.Said);
    if (Refusal.StartsWith(TEXT("It costs")) && Refusal.Contains(TEXT("transfer")))
        return FString::Printf(TEXT("Il faut %d pièces (transfert et premier salaire)."), N);
    if (Refusal.StartsWith(TEXT("It costs"))) return FString::Printf(TEXT("Il coûte %d pièces."), N);
    if (Refusal.Contains(TEXT("coins are missing"))) return FString::Printf(TEXT("Il manque %d pièces."), N);
    if (Refusal.Contains(TEXT("is not offered for breeding"))) return TEXT("Ce cheval n'est pas proposé à la reproduction.");
    if (Refusal.StartsWith(TEXT("Resting until"))) return TEXT("Au repos jusqu'à sa prochaine saillie.");
    return Refusal;
}

FString RacingStables::Apply(FHRWorldState& S, const FString& PlayerId, const FRacingStableRequest& Request)
{
    using namespace RacingStableRules;
    if (Request.Action >= uint8(ERacingStableAction::Count)) return TEXT("Cette demande n'est pas valable.");
    if (!HRRules::FindPlayer(S, PlayerId)) return TEXT("Pas de portefeuille pour ce joueur.");
    if (!HRRules::PlayerStable(S, PlayerId)) return TEXT("Vous n'avez pas encore d'écurie.");
    if (Request.Target.IsEmpty()) return TEXT("Cette demande n'est pas valable.");
    switch (ERacingStableAction(Request.Action))
    {
        case ERacingStableAction::Enter:
        case ERacingStableAction::Rest:
        {
            FString Why = HorseRefusal(S, PlayerId, Request.Target);
            if (!Why.IsEmpty()) return Why;
            const bool bEnter = ERacingStableAction(Request.Action) == ERacingStableAction::Enter;
            if (bEnter && !(Why = EntryRefusal(S, S.Horses[Request.Target])).IsEmpty()) return Why;
            HRRules::SetResting(S, PlayerId, Request.Target, !bEnter);
            return FString();
        }
        case ERacingStableAction::BuyHorse: return French(HRRules::BuyHorse(S, PlayerId, Request.Target));
        case ERacingStableAction::SellHorse: return French(HRRules::ListHorse(S, PlayerId, Request.Target, true));
        case ERacingStableAction::Withdraw: return French(HRRules::ListHorse(S, PlayerId, Request.Target, false));
        case ERacingStableAction::Breed:
            if (Request.Other.IsEmpty()) return TEXT("Choisissez le partenaire.");
            return French(HRRules::BreedPlayer(S, PlayerId, Request.Target, Request.Other, FString()));
        case ERacingStableAction::HireRider: return French(HRRules::HireRider(S, PlayerId, Request.Target));
        case ERacingStableAction::ListRider: return French(HRRules::ListRider(S, PlayerId, Request.Target, true));
        case ERacingStableAction::UnlistRider: return French(HRRules::ListRider(S, PlayerId, Request.Target, false));
        case ERacingStableAction::ReleaseRider: return French(HRRules::ReleaseRider(S, PlayerId, Request.Target));
        default: return TEXT("Cette demande n'est pas valable.");
    }
}

// ------------------------------------------------------------------------------------------------------------ views

void RacingStables::BuildView(const FHRWorldState& S, const FString& PlayerId, FRacingStableView& Out)
{
    using namespace RacingStableRules;
    Out = FRacingStableView();
    const FHRStable* St = PlayerId.IsEmpty() ? nullptr : HRRules::PlayerStable(S, PlayerId);
    const FHRPlayer* P = St ? HRRules::FindPlayer(S, PlayerId) : nullptr;
    if (!St || !P) return;
    Out.bActive = true;
    Out.bSession = ARacingService::IsSessionPlayer(PlayerId);
    const int32 Site = SiteIndexOfStable(St->Id);
    Out.Site = Site == INDEX_NONE ? FString() : FString(Sites()[Site].Id);
    Out.StableId = St->Id;
    Out.Name = St->Name;
    Out.Color = FColor::FromHex(St->Color);
    Out.Day = S.T;
    Out.Coins = P->Coins;
    Out.DailyCosts = HRRules::DailyUpkeep(S, *St);
    Out.Wages = HRRules::RiderWages(S, St->Id);
    TArray<const FHRHorse*> Horses = HRRules::StableHorses(S, St->Id);
    // Stall order: racing horses first, then the young, the retired; by id within each, so a stall keeps its horse.
    auto Rank = [&S](const FHRHorse& H) { return H.IsRetired() ? 2 : S.T < H.ReadyT ? 1 : 0; };
    Horses.Sort([&Rank](const FHRHorse& A, const FHRHorse& B) { return Rank(A) != Rank(B) ? Rank(A) < Rank(B) : A.Id < B.Id; });
    for (const FHRHorse* H : Horses)
    {
        FRacingStableHorse& V = Out.Horses.AddDefaulted_GetRef();
        V.Id = H->Id;
        V.Name = H->Name;
        V.bMare = H->bMare;
        V.Age = AgeLabel(H->BirthT, S.T);
        V.Abilities = Abilities(*H);
        V.Score = HRRules::CardScore(*H);
        V.Condition = uint8(FMath::Clamp(H->Condition, 0, 3));
        V.Starts = H->Starts;
        V.Wins = H->Wins;
        V.Podiums = H->Podiums;
        V.Earnings = H->Earnings;
        const FString Why = EntryRefusal(S, *H);
        V.bCanRace = Why.IsEmpty();
        V.bEntered = V.bCanRace && !P->Resting.Contains(H->Id);
        const FHRSaleListing* L = Listing(S, H->Id);
        V.bListed = L != nullptr;
        V.Price = L ? L->Price : HRRules::SaleValue(S, *H);
        if (H->Injury.bActive) V.Status = TEXT("Blessé, au repos");
        else if (H->IsRetired()) V.Status = TEXT("Retraité");
        else if (!V.bCanRace) V.Status = Why;
        else V.Status = V.bEntered ? TEXT("Engagé pour les réunions") : TEXT("Au repos (non engagé)");
        if (V.bListed) V.Status += FString::Printf(TEXT(" · en vente %d pièces"), V.Price);
        for (const FHRRace& R : S.Meeting.Races)
        {
            if (R.IsRun() || !R.Entries.ContainsByPredicate([H](const FHRRunner& E) { return E.HorseId == H->Id; })) continue;
            V.Today = ARacingService::RaceName(R);
            V.TodayStart = HRRules::RaceStartSeconds(S, R.Key);
            break;
        }
        const FString Breed = HRRules::BreedingAvailability(S, *H);
        V.bCanBreed = Breed.IsEmpty();
        if (const FHRPregnancy* Foal = HRRules::FindPregnancy(S, H->Id))
            V.Breeding = FString::Printf(TEXT("Pleine : poulain attendu le jour %d"), Foal->DueT);
        else V.Breeding = V.bCanBreed ? FString(TEXT("Disponible pour une saillie")) : French(Breed);
    }
    TArray<const FHRRider*> Riders = HRRules::StableRiders(S, St->Id);
    Riders.Sort([](const FHRRider& A, const FHRRider& B) { const int32 OA = HRRules::RiderOverall(A), OB = HRRules::RiderOverall(B); return OA != OB ? OA > OB : A.Id < B.Id; });
    for (const FHRRider* R : Riders) Out.Jockeys.Add(Rider(S, *R));
}

void RacingStables::BuildMarket(const FHRWorldState& S, const FString& PlayerId, FRacingStableMarket& Out)
{
    using namespace RacingStableRules;
    Out = FRacingStableMarket();
    Out.Day = S.T;
    const FHRStable* St = PlayerId.IsEmpty() ? nullptr : HRRules::PlayerStable(S, PlayerId);
    if (!St) return;
    // The transfer board: other stables' listed riders and the free agents, best first (at most ten).
    TArray<const FHRRider*> Riders;
    for (const TPair<FString, FHRRider>& It : S.Riders)
    {
        const FHRRider& R = It.Value;
        if (R.IsRetired() || R.OwnerId == St->Id) continue;
        if (R.OwnerId.IsEmpty() || R.ListedPrice > 0) Riders.Add(&R);
    }
    Riders.Sort([](const FHRRider& A, const FHRRider& B) { const int32 OA = HRRules::RiderOverall(A), OB = HRRules::RiderOverall(B); return OA != OB ? OA > OB : A.Id < B.Id; });
    for (int32 I = 0; I < FMath::Min(10, Riders.Num()); ++I) Out.Riders.Add(Rider(S, *Riders[I]));
    // The market: today's two recruits for this player, then other stables' listings (the best six).
    const TArray<FHRHorse> Recruits = HRRules::MarketRecruits(S, PlayerId);
    for (const FHRHorse& H : Recruits)
    {
        const bool bProspect = H.Id.EndsWith(TEXT(":0"));
        Out.Horses.Add(Offer(S, H, bProspect ? TEXT("market:prospect") : TEXT("market:adult"), bProspect ? HRRules::ProspectPrice : HRRules::AdultPrice,
            TEXT("Marché")));
    }
    TArray<const FHRSaleListing*> Listed;
    for (const FHRSaleListing& L : S.Listings)
        if (L.SellerId != St->Id && S.Horses.Contains(L.HorseId)) Listed.Add(&L);
    Listed.Sort([&S](const FHRSaleListing& A, const FHRSaleListing& B)
    {
        const int32 CA = HRRules::CardScore(S.Horses[A.HorseId]), CB = HRRules::CardScore(S.Horses[B.HorseId]);
        return CA != CB ? CA > CB : A.HorseId < B.HorseId;
    });
    for (int32 I = 0; I < FMath::Min(6, Listed.Num()); ++I)
        Out.Horses.Add(Offer(S, S.Horses[Listed[I]->HorseId], Listed[I]->HorseId, Listed[I]->Price, StableName(S, Listed[I]->SellerId)));
    // Partners for a covering: the best six stallions and six mares of the other stables, open to it now.
    for (const bool bMare : {false, true})
    {
        TArray<const FHRHorse*> Pool;
        for (const TPair<FString, FHRHorse>& It : S.Horses)
        {
            const FHRHorse& H = It.Value;
            const FHRStable* Owner = HRRules::FindStable(S, H.OwnerId);
            if (H.bMare != bMare || !Owner || Owner->bForSale || Owner->Id == St->Id || !HRRules::BreedingAvailability(S, H).IsEmpty()) continue;
            Pool.Add(&H);
        }
        Pool.Sort([](const FHRHorse& A, const FHRHorse& B) { const int32 CA = HRRules::CardScore(A), CB = HRRules::CardScore(B); return CA != CB ? CA > CB : A.Id < B.Id; });
        for (int32 I = 0; I < FMath::Min(6, Pool.Num()); ++I)
            Out.Studs.Add(Offer(S, *Pool[I], Pool[I]->Id, HRRules::BreedingCost(S, PlayerId, *Pool[I]), StableName(S, Pool[I]->OwnerId)));
    }
}

// ------------------------------------------------------------------------------------------------------------ world text

namespace RacingStableText
{
    const TCHAR* Condition(uint8 C)
    {
        static const TCHAR* Words[4] = {TEXT("épuisé"), TEXT("fatigué"), TEXT("en forme"), TEXT("frais")};
        return Words[FMath::Min<int32>(C, 3)];
    }

    FString Stats(const TArray<uint8>& A)
    {
        auto At = [&A](int32 I) { return A.IsValidIndex(I) ? int32(A[I]) : 0; };
        return FString::Printf(TEXT("Dép %d · Vit %d · Fond %d · Mental %d"), At(0), At(1), At(2), At(3));
    }

    /** Upper case, accented Latin-1 letters included ("Écurie de la Vallée" -> "ÉCURIE DE LA VALLÉE"). */
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
            if (C > 0xFF) C = C == 0x2019 ? TEXT('\'') : TEXT(' ');
        return Out;
    }
}

FString RacingStables::PlateText(const FRacingStableView& View, int32 Stall)
{
    using namespace RacingStableText;
    if (!View.Horses.IsValidIndex(Stall)) return FString::Printf(TEXT("Box %d\nlibre"), Stall + 1);
    const FRacingStableHorse& H = View.Horses[Stall];
    FString Text = FString::Printf(TEXT("%s\n%s · %s · note %d\n%s\nForme : %s · %d courses, %d victoires\n%s"), *Upper(H.Name),
        H.bMare ? TEXT("Jument") : TEXT("Étalon"), *H.Age, H.Score, *Stats(H.Abilities), Condition(H.Condition), H.Starts, H.Wins, *H.Status);
    if (!H.Today.IsEmpty()) Text += TEXT("\nCourt aujourd'hui : ") + H.Today;
    return Latin1(Text);
}

FString RacingStables::JockeysText(const FRacingStableView& View)
{
    // One line each, no empty line (world text draws an empty line far taller than a written one).
    TArray<FString> Lines = {TEXT("NOS JOCKEYS · ") + RacingStableText::Upper(View.Name)};
    if (View.Jockeys.IsEmpty()) Lines.Add(TEXT("Aucun jockey : voyez le tableau des transferts"));
    for (const FRacingStableRider& R : View.Jockeys)
    {
        auto At = [&R](int32 I) { return R.Stats.IsValidIndex(I) ? int32(R.Stats[I]) : 0; };
        Lines.Add(FString::Printf(TEXT("%s (%s, %d ans)%s · note %d"), *R.Name, *R.Country, R.Age, R.Legend.IsEmpty() ? TEXT("") : *(TEXT(", ") + R.Legend), R.Overall));
        Lines.Add(FString::Printf(TEXT("   Départ %d · Tactique %d · Sang-froid %d · Finish %d"), At(0), At(1), At(2), At(3)));
        Lines.Add(FString::Printf(TEXT("   %d pièces/jour · %d courses, %d victoires%s"), R.Wage, R.Rides, R.Wins,
            R.bListed ? *FString::Printf(TEXT(" · transférable %d"), R.Price) : TEXT("")));
    }
    Lines.Add(FString::Printf(TEXT("Salaires %d pièces par réunion · frais du jour %d"), View.Wages, View.DailyCosts));
    return RacingStableText::Latin1(FString::Join(Lines, TEXT("\n")));
}

FString RacingStables::TransfersText(const FRacingStableMarket& Market)
{
    TArray<FString> Lines = {TEXT("TRANSFERTS · JOCKEYS")};
    if (Market.Riders.IsEmpty()) Lines.Add(TEXT("Personne sur la liste aujourd'hui."));
    for (int32 I = 0; I < FMath::Min(6, Market.Riders.Num()); ++I)
    {
        const FRacingStableRider& R = Market.Riders[I];
        Lines.Add(FString::Printf(TEXT("%s, note %d · %s"), *R.Name, R.Overall,
            R.Stable.IsEmpty() ? *FString::Printf(TEXT("libre, %d pièces/jour"), R.Wage) : *FString::Printf(TEXT("%s, %d pièces"), *R.Stable, R.Price)));
    }
    Lines.Add(TEXT("CHEVAUX À VENDRE"));
    for (int32 I = 0; I < FMath::Min(4, Market.Horses.Num()); ++I)
    {
        const FRacingStableOffer& H = Market.Horses[I];
        Lines.Add(FString::Printf(TEXT("%s (%s, %s), note %d · %d pièces"), *H.Name, H.bMare ? TEXT("jument") : TEXT("étalon"), *H.Age, H.Score, H.Price));
    }
    return RacingStableText::Latin1(FString::Join(Lines, TEXT("\n")));
}

// ------------------------------------------------------------------------------------------------------------ anchors

bool RacingStables::BelmonteAnchors(const TSharedPtr<FJsonObject>& Places, const FVector& OriginCm, TArray<FAnchor>& Out)
{
    Out.Reset();
    // Derived from the estate's committed placement by world/regions/belmonte/build.py (BELMONTE_STABLE): Belmonte-local
    // cm round the region's origin, as the TVs; no hardcoded fallback.
    const TArray<TSharedPtr<FJsonValue>>* Rows = nullptr;
    if (!Places || !Places->TryGetArrayField(TEXT("belmonte_stable"), Rows) || !Rows) return false;
    TArray<FAnchor> Parsed;
    int32 Plates = 0, Boards = 0;
    for (const TSharedPtr<FJsonValue>& Row : *Rows)
    {
        const TSharedPtr<FJsonObject>* O = nullptr;
        FString Kind;
        FVector At, Size;
        double Yaw = 0., Stall = 0.;
        const TArray<TSharedPtr<FJsonValue>>* S = nullptr;
        if (!Row.IsValid() || !Row->TryGetObject(O) || !O || !(*O)->TryGetStringField(TEXT("kind"), Kind) ||
            !RacingPlaces::Vector(*O, TEXT("at_cm"), At) || !RacingPlaces::Number(*O, TEXT("yaw"), Yaw) ||
            !RacingPlaces::Number(*O, TEXT("stall"), Stall) || !(*O)->TryGetArrayField(TEXT("size_cm"), S) || !S || S->Num() != 2)
            return false;
        FAnchor& A = Parsed.AddDefaulted_GetRef();
        A.Kind = Kind == TEXT("plate") ? EAnchor::Plate : Kind == TEXT("jockeys") ? EAnchor::Jockeys : EAnchor::Transfers;
        if (Kind != TEXT("plate") && Kind != TEXT("jockeys") && Kind != TEXT("transfers")) return false;
        A.Stall = int32(Stall);
        if (A.Stall < 0 || A.Stall > 63) return false;
        A.At = FTransform(FRotator(0., Yaw, 0.), OriginCm + At);
        A.Size = FVector2D((*S)[0]->AsNumber(), (*S)[1]->AsNumber());
        if (!FMath::IsFinite(A.Size.X) || !FMath::IsFinite(A.Size.Y) || A.Size.X <= 0. || A.Size.Y <= 0.) return false;
        (A.Kind == EAnchor::Plate ? Plates : Boards)++;
    }
    if (!Plates || Boards != 2) return false;
    Out = MoveTemp(Parsed);
    return true;
}

bool RacingStables::HidamariAnchors(const FString& Json, TArray<FAnchor>& Out)
{
    Out.Reset();
    TSharedPtr<FJsonObject> Data;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Data) || !Data) return false;
    auto Vec = [](const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
        if (!O || !O->TryGetArrayField(Key, A)) return FVector::ZeroVector;
        return FVector(A->Num() > 0 ? (*A)[0]->AsNumber() : 0., A->Num() > 1 ? (*A)[1]->AsNumber() : 0., A->Num() > 2 ? (*A)[2]->AsNumber() : 0.);
    };
    const TSharedPtr<FJsonObject>* Site = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Stalls = nullptr;
    const TSharedPtr<FJsonObject>* Board = nullptr;
    if (!Data->TryGetObjectField(TEXT("site"), Site) || !Data->TryGetArrayField(TEXT("stalls"), Stalls) ||
        !Data->TryGetObjectField(TEXT("notice_board"), Board))
        return false;
    // As AHidamariStable places it: the stable's frame in Blender metres round the site origin, Y flipped into Unreal cm.
    const FVector Origin = Vec(*Site, TEXT("origin"));
    auto World = [&Origin](const FVector& L) { return FVector((Origin.X + L.X) * 100., -(Origin.Y + L.Y) * 100., (Origin.Z + L.Z) * 100.); };
    auto Facing = [](const FVector& N) { return FVector(N.X, -N.Y, 0.).Rotation(); };
    for (int32 I = 0; I < Stalls->Num(); ++I)
    {
        const TSharedPtr<FJsonObject> Stall = (*Stalls)[I]->AsObject();
        const TSharedPtr<FJsonObject>* Plaque = nullptr;
        if (!Stall || !Stall->TryGetObjectField(TEXT("plaque"), Plaque)) return false;
        FAnchor& A = Out.AddDefaulted_GetRef();
        A.Kind = EAnchor::Plate;
        A.Stall = I;
        A.At = FTransform(Facing(Vec(*Plaque, TEXT("normal"))), World(Vec(*Plaque, TEXT("centre"))));
        const FVector Size = Vec(*Plaque, TEXT("size"));
        A.Size = FVector2D(Size.X * 100., Size.Y * 100.);
    }
    // The office's cork board, halved: the jockeys on its left, the transfers on its right (seen from the room).
    const FRotator Rot = Facing(Vec(*Board, TEXT("normal")));
    const FVector Centre = World(Vec(*Board, TEXT("centre")));
    const FVector Size = Vec(*Board, TEXT("size")) * 100.;
    const FVector Right = FRotationMatrix(Rot).GetUnitAxis(EAxis::Y);
    for (const int32 Side : {-1, 1})
    {
        FAnchor& A = Out.AddDefaulted_GetRef();
        A.Kind = Side < 0 ? EAnchor::Jockeys : EAnchor::Transfers;
        A.At = FTransform(Rot, Centre + Right * (Side * Size.X * .25));
        A.Size = FVector2D(Size.X * .5 - 4., Size.Y);
    }
    return Out.Num() > 2;
}

bool RacingStables::SiteAnchors(const UObject* WorldContext, const FString& Site, TArray<FAnchor>& Out)
{
    Out.Reset();
    if (Site == TEXT("belmonte"))
    {
        FVector Origin;
        if (!RacingCounter::RegionOrigin(WorldContext, Origin)) return false;
        return BelmonteAnchors(RacingPlaces::Belmonte(), Origin, Out);
    }
    if (Site == TEXT("hidamari"))
    {
        // The stable's own placements (world/regions/hidamari_stable), only while Henry's AHidamariStable stands in
        // the world (its committed switch on and its import run): no plates or boards over an empty pad.
        if (!AHidamariStable::Find(WorldContext)) return false;
        static FString Cached;
        static bool bRead = false;
        if (!bRead)
        {
            bRead = true;
            FFileHelper::LoadFileToString(Cached, *AtelierDataPath(TEXT("hidamari_stable/stable.json")));
        }
        return !Cached.IsEmpty() && HidamariAnchors(Cached, Out);
    }
    return false;
}

int32 RacingStables::AnchorInReach(const TArray<FAnchor>& Anchors, const FVector& Location)
{
    int32 Best = INDEX_NONE;
    double BestDistance = 0.;
    for (int32 I = 0; I < Anchors.Num(); ++I)
    {
        const FAnchor& A = Anchors[I];
        const FVector L = A.At.InverseTransformPositionNoScale(Location);
        // In front of it (X out), within two metres, beside it and about at its height (the pawn's centre).
        if (L.X < 20. || L.X > 230. || FMath::Abs(L.Y) > A.Size.X * .5 + 40. || L.Z < -220. || L.Z > 160.) continue;
        const double D = L.X + FMath::Abs(L.Y);
        if (Best == INDEX_NONE || D < BestDistance) { Best = I; BestDistance = D; }
    }
    return Best;
}

// ------------------------------------------------------------------------------------------------------------ desk

URacingStableDesk::URacingStableDesk()
{
    PrimaryComponentTick.bCanEverTick = false;
    SetIsReplicatedByDefault(true);
}

void URacingStableDesk::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
    Super::GetLifetimeReplicatedProps(OutLifetimeProps);
    // A player's stable is theirs alone.
    DOREPLIFETIME_CONDITION(URacingStableDesk, View, COND_OwnerOnly);
    DOREPLIFETIME_CONDITION(URacingStableDesk, Market, COND_OwnerOnly);
}

void URacingStableDesk::BeginPlay()
{
    Super::BeginPlay();
    // The plates and boards are drawn by every machine that draws, for its own player.
    if (GetWorld() && GetNetMode() != NM_DedicatedServer) ARacingStableBoards::Ensure(GetWorld());
}

URacingStableDesk* URacingStableDesk::Of(const AController* Controller)
{
    return Controller ? Controller->FindComponentByClass<URacingStableDesk>() : nullptr;
}

URacingStableDesk* URacingStableDesk::Local(const UObject* WorldContext)
{
    const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
    return World ? Of(World->GetFirstPlayerController()) : nullptr;
}

void URacingStableDesk::SetBrowsing(bool bOn)
{
    if (bOn == bBrowsingAsked) return;
    bBrowsingAsked = bOn;
    const AActor* Owner = GetOwner();
    if (!Owner) return;
    if (Owner->HasAuthority()) ServerSetBrowsing_Implementation(bOn);
    else ServerSetBrowsing(bOn);
}

void URacingStableDesk::ServerSetBrowsing_Implementation(bool bOn)
{
    bBrowsing = bOn;
    if (!bOn) HostSetMarket(FRacingStableMarket());
    else if (ARacingService* Service = ARacingService::Find(this)) Service->RefreshWallets();
}

uint32 URacingStableDesk::Request(ERacingStableAction Action, const FString& Target, const FString& Other)
{
    const double Now = FPlatformTime::Seconds();
    if (PendingSeq && Now - PendingSince < 5.) return 0;
    const AActor* Owner = GetOwner();
    if (!Owner) return 0;
    FRacingStableRequest R;
    R.Seq = NextSeq++;
    R.Action = uint8(Action);
    R.Target = Target;
    R.Other = Other;
    PendingSeq = R.Seq;
    PendingSince = Now;
    if (Owner->HasAuthority()) ApplyReply(R.Seq, HostHandle(R, ARacingService::Find(this)));
    else ServerRequest(R);
    return R.Seq;
}

void URacingStableDesk::ServerRequest_Implementation(const FRacingStableRequest& Request)
{
    const double Now = FPlatformTime::Seconds();
    if (LastRequest >= 0. && Now - LastRequest < MinRequestGap)
    {
        ClientReply(Request.Seq, TEXT("Un instant, l'écurie traite votre demande."));
        return;
    }
    LastRequest = Now;
    ClientReply(Request.Seq, HostHandle(Request, ARacingService::Find(this)));
}

FString URacingStableDesk::HostHandle(const FRacingStableRequest& Request, ARacingService* Service)
{
    if (Request.Action >= uint8(ERacingStableAction::Count) || Request.Target.IsEmpty() || Request.Target.Len() > HRSave::MaxIdChars ||
        Request.Other.Len() > HRSave::MaxIdChars)
        return TEXT("Cette demande n'est pas valable.");
    if (!Service || !Service->HasWorld()) return TEXT("L'écurie est fermée pour le moment.");
    if (HostPlayerId.IsEmpty()) HostPlayerId = ARacingService::PlayerIdOf(Cast<AController>(GetOwner()));
    return Service->ApplyStableRequest(HostPlayerId, Request);
}

void URacingStableDesk::ClientReply_Implementation(uint32 Seq, const FString& Error)
{
    ApplyReply(Seq, Error);
}

void URacingStableDesk::ApplyReply(uint32 Seq, const FString& Error)
{
    if (Seq == PendingSeq) PendingSeq = 0;
    ReplySeq = Seq;
    ReplyError = Error;
    ++Revision;
}

void URacingStableDesk::HostSetView(const FRacingStableView& Next)
{
    if (FRacingStableView::StaticStruct()->CompareScriptStruct(&Next, &View, PPF_None)) return;
    View = Next;
    ++Revision;
}

void URacingStableDesk::HostSetMarket(const FRacingStableMarket& Next)
{
    if (FRacingStableMarket::StaticStruct()->CompareScriptStruct(&Next, &Market, PPF_None)) return;
    Market = Next;
    ++Revision;
}

void URacingStableDesk::OnRep_View() { ++Revision; }
void URacingStableDesk::OnRep_Market() { ++Revision; }

// ------------------------------------------------------------------------------------------------------------ boards

ARacingStableBoards::ARacingStableBoards()
{
    PrimaryActorTick.bCanEverTick = true;
    SetActorTickInterval(.25f);
    bReplicates = false;
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    static ConstructorHelpers::FObjectFinder<UMaterialInterface> Basic(TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
    BackMaterial = Basic.Object;
}

ARacingStableBoards* ARacingStableBoards::Find(const UObject* WorldContext)
{
    UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
    if (!World) return nullptr;
    TActorIterator<ARacingStableBoards> It(World);
    return It ? *It : nullptr;
}

ARacingStableBoards* ARacingStableBoards::Ensure(UWorld* World)
{
    if (!World || World->GetNetMode() == NM_DedicatedServer) return nullptr;
    if (ARacingStableBoards* Existing = Find(World)) return Existing;
    FActorSpawnParameters Params;
    Params.ObjectFlags |= RF_Transient;
    return World->SpawnActor<ARacingStableBoards>(Params);
}

void ARacingStableBoards::EndPlay(const EEndPlayReason::Type Reason)
{
    RacingStables::Close();
    Clear();
    Super::EndPlay(Reason);
}

void ARacingStableBoards::Clear()
{
    for (UStaticMeshComponent* C : Backs) if (C) C->DestroyComponent();
    for (UTextRenderComponent* C : Texts) if (C) C->DestroyComponent();
    Backs.Reset();
    Texts.Reset();
    Written = MAX_uint32;
}

void ARacingStableBoards::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    URacingStableDesk* Desk = URacingStableDesk::Local(this);
    const APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
    const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
    const FString Wanted = Desk && Desk->GetView().bActive ? Desk->GetView().Site : FString();
    if (Wanted != Site)
    {
        Clear();
        Site = Wanted;
        Anchors.Reset();
    }
    if (!Site.IsEmpty() && Anchors.IsEmpty()) RacingStables::SiteAnchors(this, Site, Anchors);
    bool bNear = false;
    if (Pawn && Anchors.Num())
        for (const RacingStables::FAnchor& A : Anchors)
            if (FVector::DistSquared(A.At.GetLocation(), Pawn->GetActorLocation()) < FMath::Square(ShowRadius)) { bNear = true; break; }
    if (Desk) Desk->SetBrowsing(bNear || RacingStables::IsOpen());
    if (!bNear) { if (Texts.Num()) Clear(); return; }
    if (Texts.IsEmpty()) Build();
    if (Desk && Desk->GetRevision() != Written) Write();
}

void ARacingStableBoards::Build()
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    for (const RacingStables::FAnchor& A : Anchors)
    {
        const bool bBoard = A.Kind != RacingStables::EAnchor::Plate;
        auto* Back = NewObject<UStaticMeshComponent>(this);
        Back->SetupAttachment(RootComponent);
        Back->SetStaticMesh(Cube);
        Back->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        Back->SetCastShadow(false);
        Back->SetCanEverAffectNavigation(false);
        // A thin board, its face 1.5 cm behind the text; the cube is 1 m across round its centre.
        Back->SetWorldTransform(FTransform(A.At.Rotator(), A.At.TransformPosition(FVector(-2.5, 0., 0.)), FVector(.02, A.Size.X / 100., A.Size.Y / 100.)));
        if (BackMaterial)
        {
            UMaterialInstanceDynamic* M = UMaterialInstanceDynamic::Create(BackMaterial, Back);
            // Forest-green plates with a brass edge feel; cork boards a warm brown.
            M->SetVectorParameterValue(TEXT("Color"), bBoard ? FLinearColor(.16f, .09f, .04f) : FLinearColor(.03f, .07f, .05f));
            Back->SetMaterial(0, M);
        }
        Back->RegisterComponent();
        Backs.Add(Back);
        auto* Text = NewObject<UTextRenderComponent>(this);
        Text->SetupAttachment(RootComponent);
        Text->SetWorldTransform(FTransform(A.At.Rotator(), A.At.TransformPosition(FVector(0., 0., 0.))));
        Text->SetHorizontalAlignment(EHTA_Center);
        Text->SetVerticalAlignment(EVRTA_TextCenter);
        Text->SetWorldSize(bBoard ? 4.f : (A.Size.Y < 40. ? 2.4f : 4.6f));
        Text->SetTextRenderColor(FColor(255, 238, 205));
        Text->SetCastShadow(false);
        Text->SetCullDistance(ShowRadius);
        Text->RegisterComponent();
        Texts.Add(Text);
    }
    Written = MAX_uint32;
}

void ARacingStableBoards::Write()
{
    const URacingStableDesk* Desk = URacingStableDesk::Local(this);
    if (!Desk) return;
    Written = Desk->GetRevision();
    for (int32 I = 0; I < Anchors.Num() && I < Texts.Num(); ++I)
    {
        const RacingStables::FAnchor& A = Anchors[I];
        const FString Text = A.Kind == RacingStables::EAnchor::Plate ? RacingStables::PlateText(Desk->GetView(), A.Stall)
            : A.Kind == RacingStables::EAnchor::Jockeys ? RacingStables::JockeysText(Desk->GetView())
            : RacingStables::TransfersText(Desk->GetMarket());
        Texts[I]->SetText(FText::FromString(Text));
    }
}

// ------------------------------------------------------------------------------------------------------------ the window

// A named namespace: in a unity build an anonymous one would leak into later files.
namespace RacingStableUi
{
    FLinearColor Hex(const TCHAR* InHex, float Alpha = 1.f)
    {
        FLinearColor Color = FLinearColor::FromSRGBColor(FColor::FromHex(InHex));
        Color.A = Alpha;
        return Color;
    }

    // The betting window's palette (the game's menus): dark forest boards, brushed brass, cream type.
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
    const FLinearColor Win = Hex(TEXT("9fd68a"));
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

    struct FPadNames { const TCHAR *Accept, *Back, *Prev, *Next, *Sort; };
    FPadNames PadNames(int32 Style)
    {
        switch (Style)
        {
            case 2: return {TEXT("Croix"), TEXT("Rond"), TEXT("L1"), TEXT("R1"), TEXT("Carré")};
            case 3: return {TEXT("B"), TEXT("A"), TEXT("L"), TEXT("R"), TEXT("Y")};
            default: return {TEXT("A"), TEXT("B"), TEXT("LB"), TEXT("RB"), TEXT("X")};
        }
    }

    enum class EPage : uint8 { Horse, Partners, Jockeys, Jockey, Riders, Market };

    struct FRow
    {
        FString Title, Sub, Right;
        /** The request it sends (Count: it opens Next instead). */
        ERacingStableAction Action = ERacingStableAction::Count;
        FString Target, Other;
        bool bEnabled = true;
        /** What the second press confirms. */
        FString Confirm;
        EPage Next = EPage::Horse;
        FString NextSubject;
    };

    /**
     * The stable's light overlay (docs/RACING.md, "Stables"): opened at a plate or a board, it lists what can be done
     * there, one row per choice. Gamepad first: up / down choose, the bottom button acts (twice: choose, then confirm),
     * the right button goes back, the bumpers change the board's tab and the left button sorts. It redraws when the
     * desk's data changes, never every frame.
     */
    class SRacingStableWindow : public SCompoundWidget
    {
    public:
        SLATE_BEGIN_ARGS(SRacingStableWindow) {}
        SLATE_END_ARGS()

        TWeakObjectPtr<URacingStableDesk> Desk;
        struct FFrame { EPage Page; FString Subject; int32 Selected = 0; };
        TArray<FFrame> Stack;
        bool bConfirm = false, bByPrice = false, bPad = false;
        uint32 Seen = MAX_uint32, Submitted = 0;
        FString Message, SubmittedText;
        bool bMessageOk = false;
        int32 PadStyle = 0;
        float StickCooldown = 0.f;
        bool bStickY = false;
        TSharedPtr<SBox> Body;
        TArray<FRow> Rows;

        void Construct(const FArguments&, URacingStableDesk* InDesk, EPage Page, const FString& Subject)
        {
            Desk = InDesk;
            Stack.Add({Page, Subject, 0});
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
                            [SAssignNew(Body, SBox).WidthOverride(560.f)]
                        ]
                    ]
                ]
            ];
            Rebuild();
        }

        FFrame& Top() { return Stack.Last(); }
        const FRacingStableView* View() const { return Desk.IsValid() ? &Desk->GetView() : nullptr; }
        const FRacingStableMarket* Market() const { return Desk.IsValid() ? &Desk->GetMarket() : nullptr; }
        const FRacingStableHorse* Horse(const FString& Id) const
        {
            const FRacingStableView* V = View();
            return V ? V->Horses.FindByPredicate([&Id](const FRacingStableHorse& H) { return H.Id == Id; }) : nullptr;
        }

        static FString Stats(const TArray<uint8>& A)
        {
            auto At = [&A](int32 I) { return A.IsValidIndex(I) ? int32(A[I]) : 0; };
            return FString::Printf(TEXT("%d / %d / %d / %d"), At(0), At(1), At(2), At(3));
        }

        // ------------------------------------------------------------ the rows of each page
        FString Title() const
        {
            const FFrame& F = Stack.Last();
            const FRacingStableView* V = View();
            switch (F.Page)
            {
                case EPage::Horse: { const FRacingStableHorse* H = Horse(F.Subject); return H ? H->Name : FString(TEXT("Box libre")); }
                case EPage::Partners: { const FRacingStableHorse* H = Horse(F.Subject); return FString::Printf(TEXT("Saillie : %s"), H ? *H->Name : TEXT("")); }
                case EPage::Jockeys: return TEXT("Nos jockeys");
                case EPage::Jockey:
                {
                    const FRacingStableRider* R = V ? V->Jockeys.FindByPredicate([&F](const FRacingStableRider& X) { return X.Id == F.Subject; }) : nullptr;
                    return R ? R->Name : FString(TEXT("Jockey"));
                }
                case EPage::Riders: return TEXT("Transferts : jockeys");
                default: return TEXT("Transferts : chevaux");
            }
        }

        void MakeRows()
        {
            Rows.Reset();
            const FRacingStableView* V = View();
            const FRacingStableMarket* M = Market();
            if (!V || !V->bActive) return;
            const FFrame& F = Stack.Last();
            switch (F.Page)
            {
                case EPage::Horse:
                {
                    const FRacingStableHorse* H = Horse(F.Subject);
                    if (!H) break;
                    FRow Entry;
                    if (H->bEntered)
                    {
                        Entry.Title = TEXT("Mettre au repos");
                        Entry.Sub = TEXT("Il ne sera pas engagé aux prochaines réunions.");
                        Entry.Action = ERacingStableAction::Rest;
                    }
                    else
                    {
                        Entry.Title = TEXT("Engager aux prochaines réunions");
                        Entry.Sub = H->bCanRace ? FString(TEXT("L'écurie le fait courir dès la prochaine réunion (trois partants au plus).")) : H->Status;
                        Entry.Action = ERacingStableAction::Enter;
                        Entry.bEnabled = H->bCanRace;
                    }
                    Entry.Target = H->Id;
                    Rows.Add(Entry);
                    FRow Sale;
                    Sale.Target = H->Id;
                    if (H->bListed)
                    {
                        Sale.Title = TEXT("Retirer de la vente");
                        Sale.Sub = FString::Printf(TEXT("En vente à %d pièces : les écuries achètent à la clôture du jour."), H->Price);
                        Sale.Action = ERacingStableAction::Withdraw;
                    }
                    else
                    {
                        Sale.Title = TEXT("Mettre en vente");
                        Sale.Right = FString::Printf(TEXT("%d pièces"), H->Price);
                        Sale.Sub = TEXT("À sa valeur ; une autre écurie l'achète, l'argent arrive dans votre bourse.");
                        Sale.Action = ERacingStableAction::SellHorse;
                        Sale.Confirm = FString::Printf(TEXT("Mettre %s en vente à %d pièces ?"), *H->Name, H->Price);
                    }
                    Rows.Add(Sale);
                    FRow Breed;
                    Breed.Title = TEXT("Faire saillir");
                    Breed.Sub = H->Breeding;
                    Breed.bEnabled = H->bCanBreed;
                    Breed.Next = EPage::Partners;
                    Breed.NextSubject = H->Id;
                    Rows.Add(Breed);
                    break;
                }
                case EPage::Partners:
                {
                    const FRacingStableHorse* H = Horse(F.Subject);
                    if (!H) break;
                    for (const FRacingStableHorse& Own : V->Horses)
                    {
                        if (Own.bMare == H->bMare || !Own.bCanBreed) continue;
                        FRow R;
                        R.Title = Own.Name;
                        R.Sub = FString::Printf(TEXT("De votre écurie · %s · note %d"), *Own.Age, Own.Score);
                        R.Right = FString::Printf(TEXT("%d"), HRRules::BreedingServiceCost);
                        R.Action = ERacingStableAction::Breed;
                        R.Target = H->Id;
                        R.Other = Own.Id;
                        R.Confirm = FString::Printf(TEXT("%s avec %s, %d pièces : poulain dans %d jours de courses."), *H->Name, *Own.Name, HRRules::BreedingServiceCost, HRRules::GestationDays);
                        Rows.Add(R);
                    }
                    if (M)
                        for (const FRacingStableOffer& O : M->Studs)
                        {
                            if (O.bMare == H->bMare) continue;
                            FRow R;
                            R.Title = O.Name;
                            R.Sub = FString::Printf(TEXT("%s · %s · note %d · %d victoires"), *O.Seller, *O.Age, O.Score, O.Wins);
                            R.Right = FString::Printf(TEXT("%d"), O.Price);
                            R.Action = ERacingStableAction::Breed;
                            R.Target = H->Id;
                            R.Other = O.Key;
                            R.Confirm = FString::Printf(TEXT("%s avec %s, %d pièces : poulain dans %d jours de courses."), *H->Name, *O.Name, O.Price, HRRules::GestationDays);
                            Rows.Add(R);
                        }
                    if (bByPrice) Rows.StableSort([](const FRow& A, const FRow& B) { return FCString::Atoi(*A.Right) < FCString::Atoi(*B.Right); });
                    break;
                }
                case EPage::Jockeys:
                    for (const FRacingStableRider& J : V->Jockeys)
                    {
                        FRow R;
                        R.Title = J.Name;
                        R.Sub = FString::Printf(TEXT("%s · %d ans · %s · %d pièces/jour%s"), *J.Country, J.Age, *Stats(J.Stats), J.Wage,
                            J.bListed ? *FString::Printf(TEXT(" · transférable %d"), J.Price) : TEXT(""));
                        R.Right = FString::Printf(TEXT("%d"), J.Overall);
                        R.Next = EPage::Jockey;
                        R.NextSubject = J.Id;
                        Rows.Add(R);
                    }
                    break;
                case EPage::Jockey:
                {
                    const FRacingStableRider* J = V->Jockeys.FindByPredicate([&F](const FRacingStableRider& X) { return X.Id == F.Subject; });
                    if (!J) break;
                    FRow List;
                    List.Target = J->Id;
                    if (J->bListed)
                    {
                        List.Title = TEXT("Retirer de la liste des transferts");
                        List.Sub = FString::Printf(TEXT("Transférable à %d pièces : une écurie peut l'acheter à la clôture du jour."), J->Price);
                        List.Action = ERacingStableAction::UnlistRider;
                    }
                    else
                    {
                        List.Title = TEXT("Mettre sur la liste des transferts");
                        List.Sub = TEXT("À sa valeur : l'écurie qui le veut paie le prix, qui arrive dans votre bourse.");
                        List.Action = ERacingStableAction::ListRider;
                        List.Confirm = FString::Printf(TEXT("Proposer %s aux autres écuries ?"), *J->Name);
                    }
                    Rows.Add(List);
                    FRow Free;
                    Free.Title = TEXT("Libérer son contrat");
                    Free.Sub = TEXT("Sans indemnité : il devient libre et son salaire s'arrête.");
                    Free.Action = ERacingStableAction::ReleaseRider;
                    Free.Target = J->Id;
                    Free.Confirm = FString::Printf(TEXT("Libérer %s ?"), *J->Name);
                    Rows.Add(Free);
                    break;
                }
                case EPage::Riders:
                    if (M)
                        for (const FRacingStableRider& J : M->Riders)
                        {
                            FRow R;
                            R.Title = J.Name + (J.Legend.IsEmpty() ? FString() : TEXT("  ·  ") + J.Legend);
                            R.Sub = FString::Printf(TEXT("%s · %d ans · %s · %s · %d pièces/jour"), *J.Country, J.Age, *Stats(J.Stats),
                                J.Stable.IsEmpty() ? TEXT("libre") : *J.Stable, J.Wage);
                            R.Right = J.Stable.IsEmpty() ? FString::Printf(TEXT("note %d · libre"), J.Overall) : FString::Printf(TEXT("note %d · %d"), J.Overall, J.Price);
                            R.Action = ERacingStableAction::HireRider;
                            R.Target = J.Id;
                            R.Confirm = J.Stable.IsEmpty()
                                ? FString::Printf(TEXT("Engager %s, libre : %d pièces par jour."), *J.Name, J.Wage)
                                : FString::Printf(TEXT("Offre à %s : %d pièces pour %s, puis environ %d pièces par jour."), *J.Stable, J.Price, *J.Name, J.Wage);
                            Rows.Add(R);
                        }
                    if (bByPrice)
                        Rows.StableSort([M](const FRow& A, const FRow& B)
                        {
                            auto Price = [M](const FString& Id) { const FRacingStableRider* R = M->Riders.FindByPredicate([&Id](const FRacingStableRider& X) { return X.Id == Id; }); return R ? R->Price : 0; };
                            return Price(A.Target) < Price(B.Target);
                        });
                    break;
                case EPage::Market:
                    if (M)
                        for (const FRacingStableOffer& O : M->Horses)
                        {
                            FRow R;
                            R.Title = O.Name;
                            R.Sub = FString::Printf(TEXT("%s · %s · %s · note %d · %s"), O.bMare ? TEXT("Jument") : TEXT("Étalon"), *O.Age, *Stats(O.Abilities), O.Score, *O.Seller);
                            R.Right = FString::Printf(TEXT("%d"), O.Price);
                            R.Action = ERacingStableAction::BuyHorse;
                            R.Target = O.Key;
                            R.Confirm = FString::Printf(TEXT("Acheter %s pour %d pièces ?"), *O.Name, O.Price);
                            Rows.Add(R);
                        }
                    if (bByPrice) Rows.StableSort([](const FRow& A, const FRow& B) { return FCString::Atoi(*A.Right) < FCString::Atoi(*B.Right); });
                    break;
            }
        }

        // ------------------------------------------------------------ actions
        void Step(int32 Delta)
        {
            if (bConfirm || Rows.IsEmpty()) return;
            Top().Selected = FMath::Clamp(Top().Selected + Delta, 0, Rows.Num() - 1);
            Rebuild();
        }
        void Tab(int32 Delta)
        {
            if (Stack.Num() != 1 || (Top().Page != EPage::Riders && Top().Page != EPage::Market)) return;
            Top() = {Top().Page == EPage::Riders ? EPage::Market : EPage::Riders, FString(), 0};
            bConfirm = false;
            Message.Reset();
            Rebuild();
        }
        void Sort() { bByPrice = !bByPrice; bConfirm = false; Rebuild(); }
        void Accept()
        {
            if (!Rows.IsValidIndex(Top().Selected) || !Desk.IsValid() || Desk->IsPending()) return;
            const FRow Row = Rows[Top().Selected];
            if (!Row.bEnabled) { Message = Row.Sub; bMessageOk = false; Rebuild(); return; }
            if (Row.Action == ERacingStableAction::Count)
            {
                Stack.Add({Row.Next, Row.NextSubject, 0});
                Message.Reset();
                Rebuild();
                return;
            }
            if (!Row.Confirm.IsEmpty() && !bConfirm) { bConfirm = true; Message.Reset(); Rebuild(); return; }
            SubmittedText = Row.Title + TEXT(" : c'est fait.");
            if (Row.Action == ERacingStableAction::Breed) SubmittedText = TEXT("Saillie faite : le poulain naîtra dans votre écurie.");
            if (Row.Action == ERacingStableAction::BuyHorse) SubmittedText = TEXT("Acheté : il arrive dans vos boxes.");
            if (Row.Action == ERacingStableAction::HireRider) SubmittedText = TEXT("Marché conclu : ce jockey monte désormais pour vous.");
            Submitted = Desk->Request(Row.Action, Row.Target, Row.Other);
            bConfirm = false;
            Message = TEXT("L'écurie s'en occupe...");
            bMessageOk = true;
            Rebuild();
        }
        /** True when the window should close. */
        bool Back()
        {
            if (bConfirm) { bConfirm = false; Rebuild(); return false; }
            if (Stack.Num() > 1) { Stack.Pop(); Message.Reset(); Rebuild(); return false; }
            return true;
        }

        // ------------------------------------------------------------ input
        virtual bool SupportsKeyboardFocus() const override { return true; }
        virtual void Tick(const FGeometry& Geometry, const double CurrentTime, const float DeltaTime) override
        {
            SCompoundWidget::Tick(Geometry, CurrentTime, DeltaTime);
            StickCooldown = FMath::Max(0.f, StickCooldown - DeltaTime);
            const int32 Style = AJapanHUD::CurrentControllerStyle();
            if (Style != PadStyle) { PadStyle = Style; bPad = Style != 0; Seen = MAX_uint32; }
            if (!Desk.IsValid()) return;
            if (Submitted && Desk->GetReplySeq() == Submitted)
            {
                const FString& Error = Desk->GetReplyError();
                bMessageOk = Error.IsEmpty();
                Message = bMessageOk ? SubmittedText : Error;
                Submitted = 0;
                Seen = MAX_uint32;
            }
            if (Desk->GetRevision() != Seen) Rebuild();
            if (FSlateApplication::IsInitialized() && !HasUserFocus(0).IsSet() && !HasUserFocusedDescendants(0))
                FSlateApplication::Get().SetUserFocus(0, SharedThis(this), EFocusCause::Navigation);
        }
        virtual FReply OnPreviewKeyDown(const FGeometry&, const FKeyEvent& E) override
        {
            const FKey K = E.GetKey();
            if (K.IsGamepadKey() != bPad) { bPad = K.IsGamepadKey(); Seen = MAX_uint32; }
            if (K == EKeys::Up || K == EKeys::W || K == EKeys::Gamepad_DPad_Up) Step(-1);
            else if (K == EKeys::Down || K == EKeys::S || K == EKeys::Gamepad_DPad_Down) Step(1);
            else if (K == EKeys::Gamepad_LeftShoulder || K == EKeys::Gamepad_RightShoulder || K == EKeys::Tab || K == EKeys::Left || K == EKeys::Right ||
                K == EKeys::Gamepad_DPad_Left || K == EKeys::Gamepad_DPad_Right) Tab(1);
            else if (K == EKeys::Gamepad_FaceButton_Left || K == EKeys::F) { if (!E.IsRepeat()) Sort(); }
            else if (K == EKeys::Enter || K == EKeys::SpaceBar || K == EKeys::Gamepad_FaceButton_Bottom || K == EKeys::Virtual_Gamepad_Accept.GetVirtualKey())
            {
                if (!E.IsRepeat()) Accept();
            }
            else if (K == EKeys::Escape || K == EKeys::BackSpace || K == EKeys::Gamepad_FaceButton_Right || K == EKeys::Virtual_Gamepad_Back.GetVirtualKey() ||
                K == EKeys::Gamepad_Special_Right || K == EKeys::Gamepad_Special_Left)
            {
                if (!E.IsRepeat() && (Back() || K == EKeys::Gamepad_Special_Right || K == EKeys::Gamepad_Special_Left)) RacingStables::Close();
            }
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
                StickCooldown = .28f;
                Step(V > 0.f ? -1 : 1);
            }
            return FReply::Handled();
        }

        // ------------------------------------------------------------ drawing
        void Rebuild()
        {
            if (!Body.IsValid()) return;
            Seen = Desk.IsValid() ? Desk->GetRevision() : 0;
            MakeRows();
            Top().Selected = Rows.IsEmpty() ? 0 : FMath::Clamp(Top().Selected, 0, Rows.Num() - 1);
            Body->SetContent(Build());
        }

        TSharedRef<SWidget> Build()
        {
            const FRacingStableView* V = View();
            TSharedRef<SVerticalBox> Root = SNew(SVerticalBox);
            Root->AddSlot().AutoHeight()
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().FillWidth(1.f)
                [
                    SNew(SVerticalBox)
                    + SVerticalBox::Slot().AutoHeight()[Text(V ? RacingStableText::Upper(V->Name) : FString(), Font("Bold", 10, 200), Gold)]
                    + SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f, 0.f, 0.f)[Text(Title(), Font("Bold", 22), Cream)]
                ]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                [Text(V ? FString::Printf(TEXT("%d pièces"), V->Coins) : FString(), Font("Bold", 16), Gold)]
            ];
            // The subject's own line: a horse's stats, the stable's daily costs, the board's tab.
            FString Line;
            const FFrame& F = Stack.Last();
            if (F.Page == EPage::Horse || F.Page == EPage::Partners)
            {
                if (const FRacingStableHorse* H = Horse(F.Subject))
                    Line = FString::Printf(TEXT("%s · %s · note %d · %s\n%s%s"), H->bMare ? TEXT("Jument") : TEXT("Étalon"), *H->Age, H->Score, *Stats(H->Abilities),
                        *H->Status, H->Today.IsEmpty() ? TEXT("") : *(TEXT("\nCourt aujourd'hui : ") + H->Today));
            }
            else if (V && (F.Page == EPage::Jockeys || F.Page == EPage::Jockey))
                Line = FString::Printf(TEXT("Salaires : %d pièces par réunion, payés à la clôture avec l'entretien (%d en tout)."), V->Wages, V->DailyCosts);
            else
                Line = F.Page == EPage::Riders ? TEXT("Jockeys sur la liste et jockeys libres") : TEXT("Le marché du jour et les chevaux des autres écuries");
            Root->AddSlot().AutoHeight().Padding(0.f, 6.f, 0.f, 10.f)[Text(Line, Font("Regular", 12), Sage, true)];
            Root->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 10.f)[SNew(SBox).HeightOverride(1.f)[SNew(SImage).Image(Rounded(BrassSoft, 0.f))]];
            if (Rows.IsEmpty())
                Root->AddSlot().AutoHeight()[Text(F.Page == EPage::Partners ? TEXT("Aucun partenaire disponible pour le moment.") : TEXT("Rien à faire ici pour le moment."), Font("Regular", 13), Muted)];
            // At most seven rows round the selection.
            const int32 First = FMath::Clamp(Top().Selected - 3, 0, FMath::Max(0, Rows.Num() - 7));
            for (int32 I = First; I < FMath::Min(Rows.Num(), First + 7); ++I)
            {
                const FRow& R = Rows[I];
                const bool bSel = I == Top().Selected;
                TWeakPtr<SRacingStableWindow> Self = SharedThis(this);
                Root->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 5.f)
                [
                    SNew(SButton).ButtonStyle(&FCoreStyle::Get().GetWidgetStyle<FButtonStyle>("NoBorder")).ContentPadding(0)
                    .OnClicked_Lambda([Self, I] { if (auto W = Self.Pin()) { if (W->Top().Selected == I) W->Accept(); else if (!W->bConfirm) { W->Top().Selected = I; W->Rebuild(); } } return FReply::Handled(); })
                    [
                        SNew(SBorder).BorderImage(Rounded(bSel ? PlaqueSelected : Plaque, 8.f, bSel ? Brass : BrassFaint, bSel ? 1.5f : 1.f)).Padding(FMargin(12.f, 7.f))
                        [
                            SNew(SHorizontalBox)
                            + SHorizontalBox::Slot().FillWidth(1.f)
                            [
                                SNew(SVerticalBox)
                                + SVerticalBox::Slot().AutoHeight()[Text(R.Title, Font("Bold", 14), R.bEnabled ? (bSel ? Cream : Sage) : Muted)]
                                + SVerticalBox::Slot().AutoHeight()[Text(R.Sub, Font("Regular", 11), Muted, true)]
                            ]
                            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(10.f, 0.f, 0.f, 0.f)
                            [Text(R.Right, Font("Bold", 15), bSel ? Gold : BrassSoft)]
                        ]
                    ]
                ];
            }
            if (bConfirm && Rows.IsValidIndex(Top().Selected))
                Root->AddSlot().AutoHeight().Padding(0.f, 6.f, 0.f, 0.f)
                [
                    SNew(SBorder).BorderImage(Rounded(Hex(TEXT("2a2414")), 9.f, Gold, 1.5f)).Padding(FMargin(14.f, 9.f))
                    [Text(Rows[Top().Selected].Confirm, Font("Bold", 13), Cream, true)]
                ];
            if (!Message.IsEmpty())
                Root->AddSlot().AutoHeight().Padding(2.f, 8.f, 0.f, 0.f)[Text(Message, Font("Bold", 12), bMessageOk ? Win : Loss, true)];
            const FPadNames Pad = PadNames(PadStyle == 0 ? 1 : PadStyle);
            const bool bTabs = Stack.Num() == 1 && (F.Page == EPage::Riders || F.Page == EPage::Market);
            const bool bSorts = F.Page == EPage::Riders || F.Page == EPage::Market || F.Page == EPage::Partners;
            FString Legend = bPad ? FString::Printf(TEXT("Haut / Bas  Choisir   ·   %s  %s   ·   %s  %s"), Pad.Accept, bConfirm ? TEXT("Confirmer") : TEXT("Valider"),
                                        Pad.Back, bConfirm ? TEXT("Annuler") : Stack.Num() > 1 ? TEXT("Retour") : TEXT("Fermer"))
                                  : FString::Printf(TEXT("↑ / ↓  Choisir   ·   Entrée  %s   ·   Échap  %s"), bConfirm ? TEXT("Confirmer") : TEXT("Valider"),
                                        bConfirm ? TEXT("Annuler") : Stack.Num() > 1 ? TEXT("Retour") : TEXT("Fermer"));
            if (bTabs) Legend += bPad ? FString::Printf(TEXT("   ·   %s / %s  Jockeys / Chevaux"), Pad.Prev, Pad.Next) : FString(TEXT("   ·   Tab  Jockeys / Chevaux"));
            if (bSorts) Legend += FString::Printf(TEXT("   ·   %s  Trier par %s"), bPad ? Pad.Sort : TEXT("F"), bByPrice ? TEXT("note") : TEXT("prix"));
            Root->AddSlot().AutoHeight().Padding(0.f, 12.f, 0.f, 0.f)[Text(Legend, Font("Regular", 11), Hex(TEXT("f3e8d2")), true)];
            return Root;
        }

        FString Json() const
        {
            const TCHAR* Pages[] = {TEXT("horse"), TEXT("partners"), TEXT("jockeys"), TEXT("jockey"), TEXT("riders"), TEXT("market")};
            const FFrame& F = Stack.Last();
            FString List;
            for (const FRow& R : Rows)
                List += FString::Printf(TEXT("%s{\"title\":\"%s\",\"action\":%d,\"target\":\"%s\",\"other\":\"%s\",\"enabled\":%s}"), List.IsEmpty() ? TEXT("") : TEXT(","),
                    *RacingJsonEscape(R.Title), int32(R.Action), *RacingJsonEscape(R.Target), *RacingJsonEscape(R.Other),
                    R.bEnabled ? TEXT("true") : TEXT("false"));
            return FString::Printf(TEXT("{\"page\":\"%s\",\"subject\":\"%s\",\"selected\":%d,\"confirm\":%s,\"by_price\":%s,\"message\":\"%s\",\"rows\":[%s]}"),
                Pages[uint8(F.Page)], *RacingJsonEscape(F.Subject), F.Selected, bConfirm ? TEXT("true") : TEXT("false"), bByPrice ? TEXT("true") : TEXT("false"),
                *RacingJsonEscape(Message), *List);
        }
    };

    struct FOpen
    {
        TSharedPtr<SRacingStableWindow> Window;
        TWeakObjectPtr<AWandererCharacter> Player;
    };
    FOpen& Open()
    {
        static FOpen State;
        return State;
    }

    /** The anchor of the local player's stable within reach, or INDEX_NONE. */
    int32 InReach(const AWandererCharacter* Pawn, const ARacingStableBoards*& OutBoards)
    {
        OutBoards = nullptr;
        if (!Pawn || !Pawn->IsLocallyControlled() || !Pawn->IsReady() || Pawn->IsMenuOpen() || RacingStables::IsOpen() || RacingCounter::IsOpen() ||
            Pawn->OnVehicle() || Pawn->IsZeppelinPassenger() || (Pawn->GetSkate() && Pawn->GetSkate()->IsRiding()))
            return INDEX_NONE;
        const URacingStableDesk* Desk = URacingStableDesk::Of(Pawn->GetController());
        OutBoards = ARacingStableBoards::Find(Pawn);
        if (!Desk || !Desk->GetView().bActive || !OutBoards || !OutBoards->NumShown()) return INDEX_NONE;
        return RacingStables::AnchorInReach(OutBoards->GetAnchors(), Pawn->GetActorLocation());
    }
}

FString RacingStables::Prompt(const AWandererCharacter* Pawn)
{
    const ARacingStableBoards* Boards = nullptr;
    const int32 I = RacingStableUi::InReach(Pawn, Boards);
    if (I == INDEX_NONE) return FString();
    const FAnchor& A = Boards->GetAnchors()[I];
    if (A.Kind == EAnchor::Jockeys) return TEXT("Tableau des jockeys");
    if (A.Kind == EAnchor::Transfers) return TEXT("Transferts et marché");
    const FRacingStableView& View = URacingStableDesk::Of(Pawn->GetController())->GetView();
    return View.Horses.IsValidIndex(A.Stall) ? FString::Printf(TEXT("Box %d : %s"), A.Stall + 1, *View.Horses[A.Stall].Name) : FString();
}

bool RacingStables::TryOpen(AWandererCharacter* Pawn)
{
    using namespace RacingStableUi;
    const ARacingStableBoards* Boards = nullptr;
    const int32 I = InReach(Pawn, Boards);
    if (I == INDEX_NONE || !GEngine || !GEngine->GameViewport) return false;
    URacingStableDesk* Desk = URacingStableDesk::Of(Pawn->GetController());
    const FAnchor& A = Boards->GetAnchors()[I];
    EPage Page = EPage::Horse;
    FString Subject;
    if (A.Kind == EAnchor::Jockeys) Page = EPage::Jockeys;
    else if (A.Kind == EAnchor::Transfers) Page = EPage::Riders;
    else if (Desk->GetView().Horses.IsValidIndex(A.Stall)) Subject = Desk->GetView().Horses[A.Stall].Id;
    else return false;   // an empty stall: nothing to do there
    FOpen& State = Open();
    Desk->SetBrowsing(true);
    State.Window = SNew(SRacingStableWindow, Desk, Page, Subject);
    State.Player = Pawn;
    GEngine->GameViewport->AddViewportWidgetContent(State.Window.ToSharedRef(), 22);
    Pawn->SetMenuOpen(true);
    FSlateApplication::Get().SetUserFocus(0, State.Window, EFocusCause::SetDirectly);
    UE_LOG(LogTemp, Display, TEXT("RACING STABLE window open (%s %s)"), A.Kind == EAnchor::Plate ? TEXT("plate") : A.Kind == EAnchor::Jockeys ? TEXT("jockeys") : TEXT("transfers"), *Subject);
    return true;
}

bool RacingStables::IsOpen()
{
    return RacingStableUi::Open().Window.IsValid();
}

void RacingStables::Close()
{
    RacingStableUi::FOpen& State = RacingStableUi::Open();
    if (!State.Window.IsValid()) return;
    if (GEngine && GEngine->GameViewport) GEngine->GameViewport->RemoveViewportWidgetContent(State.Window.ToSharedRef());
    State.Window.Reset();
    if (AWandererCharacter* Pawn = State.Player.Get()) Pawn->SetMenuOpen(false);
    State.Player.Reset();
    UE_LOG(LogTemp, Display, TEXT("RACING STABLE window closed"));
}

FString RacingStables::WindowJson()
{
    const RacingStableUi::FOpen& State = RacingStableUi::Open();
    return State.Window.IsValid() ? State.Window->Json() : FString(TEXT("null"));
}

bool RacingStables::GoTo(AWandererCharacter* Pawn, const FString& Spot)
{
    const URacingStableDesk* Desk = Pawn ? URacingStableDesk::Of(Pawn->GetController()) : nullptr;
    TArray<FAnchor> Anchors;
    if (!Desk || !Desk->GetView().bActive || !SiteAnchors(Pawn, Desk->GetView().Site, Anchors)) return false;
    int32 Index = INDEX_NONE;
    if (Spot.StartsWith(TEXT("plate")))
    {
        const int32 Stall = FCString::Atoi(*Spot.Mid(5).TrimStartAndEnd());
        Index = Anchors.IndexOfByPredicate([Stall](const FAnchor& A) { return A.Kind == EAnchor::Plate && A.Stall == Stall; });
    }
    else
    {
        const EAnchor Kind = Spot.StartsWith(TEXT("jock")) ? EAnchor::Jockeys : EAnchor::Transfers;
        Index = Anchors.IndexOfByPredicate([Kind](const FAnchor& A) { return A.Kind == Kind; });
    }
    if (Index == INDEX_NONE) return false;
    // A metre and a half in front of it, facing it, on the ground below.
    const FAnchor& A = Anchors[Index];
    const FVector Stand = A.At.TransformPosition(FVector(150., 0., 0.));
    return Pawn->TravelTo(FVector(Stand.X, Stand.Y, Stand.Z - 60.), A.At.Rotator().Yaw + 180.f, TEXT("racing stable"), 150.f);
}

static FAutoConsoleCommandWithWorldAndArgs RacingStableCommand(TEXT("racing.Stable"),
    TEXT("racing.Stable plate <n>|jockeys|transfers: stand before a plate or a board of your stable"),
    FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
    {
        APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
        RacingStables::GoTo(PC ? Cast<AWandererCharacter>(PC->GetPawn()) : nullptr, FString::Join(Args, TEXT(" ")));
    }));

// ------------------------------------------------------------------------------------------------------------ live

FString URacingStableLive::RacingStable()
{
    const URacingStableDesk* Desk = URacingStableDesk::Local(ULiveLibrary::GameWorld());
    if (!Desk) return TEXT("{}");
    const FRacingStableView& V = Desk->GetView();
    auto E = [](const FString& T) { return RacingJsonEscape(T); };
    FString Horses, Jockeys, Riders, Market;
    for (const FRacingStableHorse& H : V.Horses)
        Horses += FString::Printf(TEXT("%s{\"id\":\"%s\",\"name\":\"%s\",\"mare\":%s,\"score\":%d,\"entered\":%s,\"can_race\":%s,\"listed\":%s,\"price\":%d,\"can_breed\":%s,\"status\":\"%s\",\"today\":\"%s\",\"breeding\":\"%s\"}"),
            Horses.IsEmpty() ? TEXT("") : TEXT(","), *E(H.Id), *E(H.Name), H.bMare ? TEXT("true") : TEXT("false"), H.Score, H.bEntered ? TEXT("true") : TEXT("false"),
            H.bCanRace ? TEXT("true") : TEXT("false"), H.bListed ? TEXT("true") : TEXT("false"), H.Price, H.bCanBreed ? TEXT("true") : TEXT("false"), *E(H.Status), *E(H.Today), *E(H.Breeding));
    auto RiderJson = [&E](const FRacingStableRider& R)
    {
        return FString::Printf(TEXT("{\"id\":\"%s\",\"name\":\"%s\",\"stable\":\"%s\",\"overall\":%d,\"wage\":%d,\"price\":%d,\"listed\":%s}"), *E(R.Id), *E(R.Name), *E(R.Stable),
            R.Overall, R.Wage, R.Price, R.bListed ? TEXT("true") : TEXT("false"));
    };
    for (const FRacingStableRider& R : V.Jockeys) Jockeys += (Jockeys.IsEmpty() ? TEXT("") : TEXT(",")) + RiderJson(R);
    for (const FRacingStableRider& R : Desk->GetMarket().Riders) Riders += (Riders.IsEmpty() ? TEXT("") : TEXT(",")) + RiderJson(R);
    for (const FRacingStableOffer& O : Desk->GetMarket().Horses)
        Market += FString::Printf(TEXT("%s{\"key\":\"%s\",\"name\":\"%s\",\"price\":%d,\"seller\":\"%s\"}"), Market.IsEmpty() ? TEXT("") : TEXT(","), *E(O.Key), *E(O.Name), O.Price, *E(O.Seller));
    const ARacingStableBoards* Boards = ARacingStableBoards::Find(ULiveLibrary::GameWorld());
    const AWandererCharacter* Pawn = Cast<AWandererCharacter>(ULiveLibrary::Player());
    return FString::Printf(TEXT("{\"active\":%s,\"session\":%s,\"site\":\"%s\",\"stable\":\"%s\",\"name\":\"%s\",\"coins\":%d,\"daily_costs\":%d,\"wages\":%d,"
        "\"horses\":[%s],\"jockeys\":[%s],\"market_riders\":[%s],\"market_horses\":[%s],\"studs\":%d,\"boards_shown\":%d,\"prompt\":\"%s\",\"pending\":%s,"
        "\"reply\":{\"seq\":%u,\"error\":\"%s\"},\"window\":%s}"),
        V.bActive ? TEXT("true") : TEXT("false"), V.bSession ? TEXT("true") : TEXT("false"), *E(V.Site), *E(V.StableId), *E(V.Name), V.Coins, V.DailyCosts, V.Wages,
        *Horses, *Jockeys, *Riders, *Market, Desk->GetMarket().Studs.Num(), Boards ? Boards->NumShown() : 0, *E(RacingStables::Prompt(Pawn)),
        Desk->IsPending() ? TEXT("true") : TEXT("false"), Desk->GetReplySeq(), *E(Desk->GetReplyError()), *RacingStables::WindowJson());
}

bool URacingStableLive::RacingStableGo(const FString& Spot)
{
    return RacingStables::GoTo(Cast<AWandererCharacter>(ULiveLibrary::Player()), Spot);
}

bool URacingStableLive::RacingStableOpen()
{
    return RacingStables::TryOpen(Cast<AWandererCharacter>(ULiveLibrary::Player()));
}

int32 URacingStableLive::RacingStableAct(const FString& Action, const FString& Target, const FString& Other)
{
    static const TMap<FString, ERacingStableAction> Names = {
        {TEXT("enter"), ERacingStableAction::Enter}, {TEXT("rest"), ERacingStableAction::Rest}, {TEXT("buy"), ERacingStableAction::BuyHorse},
        {TEXT("sell"), ERacingStableAction::SellHorse}, {TEXT("withdraw"), ERacingStableAction::Withdraw}, {TEXT("breed"), ERacingStableAction::Breed},
        {TEXT("hire"), ERacingStableAction::HireRider}, {TEXT("list"), ERacingStableAction::ListRider}, {TEXT("unlist"), ERacingStableAction::UnlistRider},
        {TEXT("release"), ERacingStableAction::ReleaseRider}};
    URacingStableDesk* Desk = URacingStableDesk::Local(ULiveLibrary::GameWorld());
    const ERacingStableAction* A = Names.Find(Action.ToLower());
    return Desk && A ? int32(Desk->Request(*A, Target, Other)) : 0;
}
