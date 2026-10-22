#include "RacingNetworkQA.h"
#include "BelmonteTrainService.h"
#include "HRRules.h"
#include "JapanSession.h"
#include "RacingBetting.h"
#include "RacingBroadcast.h"
#include "RacingRecords.h"
#include "RacingService.h"
#include "RacingStables.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonSerializer.h"
#include "UnrealClient.h"

namespace RacingNetworkQA
{
    enum class EStep : uint8
    {
        // guest
        Wait, Identity, StableRest, StableEnter, Records, RecordsCard, Bet, Race, Leave, Away, Rejoin,
        // host
        HostWait, HostRace, HostGuestAway, HostGuestBack,
        Done
    };

    struct FState
    {
        bool bStarted = false, bServer = false, bRejoining = false;
        EStep Step = EStep::Wait;
        FString Folder;
        double StepAt = 0., NextSample = 0., NextTrain = 0.;
        uint32 Seq = 0;
        TSharedPtr<FJsonObject> Report;
        TArray<TSharedPtr<FJsonValue>> Checks, RaceSamples, TrainSamples, Fps;
        // frame rate over each second
        double FpsFrom = 0.;
        int32 Frames = 0;
        // guest
        FString Horse, StatusBefore, RaceKey, Address;
        TArray<FString> Runners, Tickets;
        int32 Bets = 0, CoinsBeforeBets = 0;
        double RaceStart = 0.;
        TSharedPtr<FJsonObject> BeforeLeave;
        // host
        FString GuestKey;
        bool bTv = false, bTvShot = false, bResultShot = false;
    };

    FState& S() { static FState State; return State; }

    double Wall() { return double((FDateTime::UtcNow() - FDateTime(1970, 1, 1)).GetTicks()) / double(ETimespan::TicksPerSecond); }

    void Check(const FString& Name, bool bPass, const FString& Detail = FString())
    {
        auto C = MakeShared<FJsonObject>();
        C->SetStringField(TEXT("name"), Name);
        C->SetBoolField(TEXT("pass"), bPass);
        C->SetStringField(TEXT("detail"), Detail);
        S().Checks.Add(MakeShared<FJsonValueObject>(C));
        UE_LOG(LogTemp, Display, TEXT("RACING QA %s %s: %s"), bPass ? TEXT("PASS") : TEXT("FAIL"), *Name, *Detail);
    }

    bool Write()
    {
        FState& St = S();
        St.Report->SetStringField(TEXT("role"), St.bServer ? TEXT("server") : TEXT("client"));
        St.Report->SetNumberField(TEXT("step"), int32(St.Step));
        St.Report->SetBoolField(TEXT("done"), St.Step == EStep::Done);
        St.Report->SetStringField(TEXT("install"), ARacingService::LocalInstallId());
        St.Report->SetArrayField(TEXT("checks"), St.Checks);
        St.Report->SetArrayField(TEXT("race"), St.RaceSamples);
        St.Report->SetArrayField(TEXT("train"), St.TrainSamples);
        St.Report->SetArrayField(TEXT("fps"), St.Fps);
        FString Json;
        FJsonSerializer::Serialize(St.Report.ToSharedRef(), TJsonWriterFactory<>::Create(&Json));
        const FString Path = St.Folder / (FString(TEXT("racing-")) + (St.bServer ? TEXT("server") : TEXT("client")) + TEXT(".json"));
        const FString Temporary = Path + TEXT(".tmp");
        return FFileHelper::SaveStringToFile(Json, *Temporary) && IFileManager::Get().Move(*Path, *Temporary, true, true);
    }

    /** A capture of this machine's view, when it renders (-networkrender). */
    void Shot(const FString& Name)
    {
        if (!FParse::Param(FCommandLine::Get(), TEXT("networkrender"))) return;
        const FString Path = S().Folder / FString::Printf(TEXT("racing-%s-%s.png"), S().bServer ? TEXT("host") : TEXT("guest"), *Name);
        FScreenshotRequest::RequestScreenshot(Path, false, false);
        UE_LOG(LogTemp, Display, TEXT("RACING QA shot %s"), *Path);
    }

    void Go(EStep Next)
    {
        FState& St = S();
        St.Step = Next;
        St.StepAt = FPlatformTime::Seconds();
        Write();
    }

    TSharedPtr<FJsonObject> WalletJson(const URacingWallet* Wallet)
    {
        auto O = MakeShared<FJsonObject>();
        if (!Wallet) return O;
        const FRacingWalletView& V = Wallet->GetView();
        O->SetBoolField(TEXT("active"), V.bActive);
        O->SetBoolField(TEXT("session"), V.bSession);
        O->SetNumberField(TEXT("coins"), V.Coins);
        TArray<TSharedPtr<FJsonValue>> Tickets;
        for (const FRacingTicketView& T : V.Tickets)
        {
            auto X = MakeShared<FJsonObject>();
            X->SetStringField(TEXT("id"), T.Id);
            X->SetStringField(TEXT("horse"), T.Horse);
            X->SetNumberField(TEXT("stake"), T.Stake);
            X->SetNumberField(TEXT("status"), T.Status);
            X->SetNumberField(TEXT("payout"), T.Payout);
            Tickets.Add(MakeShared<FJsonValueObject>(X));
        }
        O->SetArrayField(TEXT("tickets"), Tickets);
        return O;
    }

    TSharedPtr<FJsonObject> StableJson(const URacingStableDesk* Desk)
    {
        auto O = MakeShared<FJsonObject>();
        if (!Desk) return O;
        const FRacingStableView& V = Desk->GetView();
        O->SetBoolField(TEXT("active"), V.bActive);
        O->SetBoolField(TEXT("session"), V.bSession);
        O->SetStringField(TEXT("site"), V.Site);
        O->SetStringField(TEXT("stable"), V.StableId);
        TArray<TSharedPtr<FJsonValue>> Horses;
        for (const FRacingStableHorse& H : V.Horses) Horses.Add(MakeShared<FJsonValueString>(H.Id));
        O->SetArrayField(TEXT("horses"), Horses);
        return O;
    }

    /** The race in focus and every runner's position at this machine's world now, and the train line. */
    void Sample(UWorld* World)
    {
        FState& St = S();
        const double Now = FPlatformTime::Seconds();
        ++St.Frames;
        if (St.FpsFrom <= 0.) St.FpsFrom = Now;
        if (Now - St.FpsFrom >= 1.)
        {
            auto F = MakeShared<FJsonObject>();
            F->SetNumberField(TEXT("wall"), Wall());
            F->SetNumberField(TEXT("fps"), St.Frames / (Now - St.FpsFrom));
            F->SetNumberField(TEXT("step"), int32(St.Step));
            St.Fps.Add(MakeShared<FJsonValueObject>(F));
            St.Frames = 0;
            St.FpsFrom = Now;
        }
        const ARacingService* Service = ARacingService::Find(World);
        if (Service && Now >= St.NextSample)
        {
            const FRacingNetRace& Race = Service->GetNetState().Race;
            const double WorldNow = Service->WorldNow();
            // Two samples a second from a little before the start until a little after the result.
            if (!Race.Key.IsEmpty() && WorldNow > Race.Start - 3. && WorldNow < Race.Start + 240.)
            {
                St.NextSample = Now + .5;
                auto R = MakeShared<FJsonObject>();
                R->SetNumberField(TEXT("wall"), Wall());
                R->SetNumberField(TEXT("world"), WorldNow);
                R->SetStringField(TEXT("race"), Race.Key);
                R->SetNumberField(TEXT("start"), Race.Start);
                R->SetNumberField(TEXT("serial"), Service->GetNetState().Serial);
                R->SetStringField(TEXT("last"), Service->GetNetState().Last.Key);
                TArray<TSharedPtr<FJsonValue>> Where, Grid;
                for (int32 I = 0; I < Race.Runners.Num(); ++I)
                {
                    FVector At;
                    float Yaw = 0.f;
                    double Speed = 0.;
                    const bool bOk = Service->RunnerAt(Race, I, WorldNow, At, Yaw, Speed);
                    TArray<TSharedPtr<FJsonValue>> P{MakeShared<FJsonValueNumber>(bOk ? At.X : 0.), MakeShared<FJsonValueNumber>(bOk ? At.Y : 0.),
                        MakeShared<FJsonValueNumber>(bOk ? At.Z : 0.)};
                    Where.Add(MakeShared<FJsonValueArray>(P));
                    // The same runner at a world second both machines sample: the race data itself, independent of the clock.
                    const double Fixed = Race.Start + FMath::FloorToDouble(WorldNow - Race.Start);
                    Service->RunnerAt(Race, I, Fixed, At, Yaw, Speed);
                    TArray<TSharedPtr<FJsonValue>> Q{MakeShared<FJsonValueNumber>(Fixed), MakeShared<FJsonValueNumber>(At.X),
                        MakeShared<FJsonValueNumber>(At.Y), MakeShared<FJsonValueNumber>(At.Z)};
                    Grid.Add(MakeShared<FJsonValueArray>(Q));
                }
                R->SetArrayField(TEXT("runners"), Where);
                R->SetArrayField(TEXT("grid"), Grid);
                St.RaceSamples.Add(MakeShared<FJsonValueObject>(R));
            }
        }
        if (Now >= St.NextTrain)
        {
            St.NextTrain = Now + 1.;
            if (const ABelmonteTrainService* Train = ABelmonteTrainService::Find(World))
            {
                const FBelmonteTrainLine& Line = Train->GetLine();
                const double Time = Train->ServiceTime();
                auto T = MakeShared<FJsonObject>();
                T->SetNumberField(TEXT("wall"), Wall());
                T->SetNumberField(TEXT("time"), Time);
                TArray<TSharedPtr<FJsonValue>> Chainages;
                for (int32 I = 0; I < Line.Trains.Num(); ++I) Chainages.Add(MakeShared<FJsonValueNumber>(Line.Chainage(I, Time)));
                T->SetArrayField(TEXT("chainage"), Chainages);
                // What a station board counts down: the next crossing and the next train through the line's origin.
                const double Crossing = Line.NextCrossing(Time);
                const double Passing = Line.NextPassing(Time, 0.);
                T->SetNumberField(TEXT("crossing_in"), Crossing >= 0. ? Crossing - Time : -1.);
                T->SetNumberField(TEXT("passing_in"), Passing >= 0. ? Passing - Time : -1.);
                St.TrainSamples.Add(MakeShared<FJsonValueObject>(T));
            }
        }
    }

    bool TimedOut(double Seconds, const TCHAR* What, FString& Error)
    {
        if (FPlatformTime::Seconds() - S().StepAt < Seconds) return false;
        Error = FString::Printf(TEXT("Racing QA: %s did not happen within %.0f s"), What, Seconds);
        Check(What, false, TEXT("timed out"));
        Write();
        return true;
    }

    bool Connected(UWorld* World)
    {
        if (!World || World->GetNetMode() != NM_Client) return false;
        const APlayerController* PC = World->GetFirstPlayerController();
        const URacingWallet* Wallet = URacingWallet::Local(World);
        const URacingStableDesk* Desk = URacingStableDesk::Local(World);
        return PC && PC->GetPawn() && Wallet && Wallet->GetView().bActive && Desk && Desk->GetView().bActive;
    }

    bool TickGuest(UJapanGameInstance* Session, UWorld* World, FString& Error)
    {
        FState& St = S();
        URacingWallet* Wallet = URacingWallet::Local(World);
        URacingStableDesk* Desk = URacingStableDesk::Local(World);
        URacingRecordsDesk* Records = URacingRecordsDesk::Local(World);
        const ARacingService* Service = ARacingService::Find(World);
        switch (St.Step)
        {
        case EStep::Wait:
            if (!Connected(World)) return !TimedOut(150., TEXT("the guest's wallet and stable"), Error) && false;
            Go(EStep::Identity);
            return false;
        case EStep::Identity:
        {
            const FRacingWalletView& W = Wallet->GetView();
            const FRacingStableView& V = Desk->GetView();
            St.Report->SetObjectField(TEXT("first_wallet"), WalletJson(Wallet));
            St.Report->SetObjectField(TEXT("first_stable"), StableJson(Desk));
            Check(TEXT("guest wallet kept across sessions"), W.bActive && !W.bSession, FString::Printf(TEXT("coins %d"), W.Coins));
            Check(TEXT("guest stable is Hidamari"), V.Site == TEXT("hidamari") && !V.bSession, V.Site + TEXT(" / ") + V.StableId);
            Shot(TEXT("1-joined"));
            if (V.Horses.IsEmpty()) { Check(TEXT("guest stable has a horse"), false); Go(EStep::Records); return false; }
            St.Horse = V.Horses[0].Id;
            St.StatusBefore = V.Horses[0].Status;
            Desk->SetBrowsing(true);
            St.Seq = Desk->Request(ERacingStableAction::Rest, St.Horse);
            Go(EStep::StableRest);
            return false;
        }
        case EStep::StableRest:
        case EStep::StableEnter:
        {
            const bool bRest = St.Step == EStep::StableRest;
            if (!St.Seq) { St.Seq = Desk->Request(bRest ? ERacingStableAction::Rest : ERacingStableAction::Enter, St.Horse); return false; }
            if (Desk->GetReplySeq() != St.Seq) return !TimedOut(10., TEXT("the stable's answer"), Error) && false;
            const FRacingStableHorse* H = Desk->GetView().Horses.FindByPredicate([&St](const FRacingStableHorse& X) { return X.Id == St.Horse; });
            // The view follows within the host's next refresh (twice a second).
            if (FPlatformTime::Seconds() - St.StepAt < 1.5) return false;
            Check(bRest ? TEXT("stable request: rest a horse") : TEXT("stable request: enter it again"), Desk->GetReplyError().IsEmpty(),
                FString::Printf(TEXT("reply '%s', status '%s' -> '%s'"), *Desk->GetReplyError(), *St.StatusBefore, H ? *H->Status : TEXT("?")));
            if (bRest)
            {
                Check(TEXT("stable view shows the change"), H && H->Status != St.StatusBefore, H ? H->Status : FString());
                St.Seq = Desk->Request(ERacingStableAction::Enter, St.Horse);
                Go(EStep::StableEnter);
            }
            else
            {
                Desk->SetBrowsing(false);
                FRacingRecordsQuery Q;
                Q.Object = uint8(ERacingHallObject::Cabinet);
                Q.Sort = 1;
                St.Seq = Records ? Records->Ask(Q) : 0;
                Go(EStep::Records);
            }
            return false;
        }
        case EStep::Records:
        case EStep::RecordsCard:
        {
            const bool bCard = St.Step == EStep::RecordsCard;
            if (!Records) { Check(TEXT("records desk"), false); Go(EStep::Bet); return false; }
            if (!St.Seq)
            {
                FRacingRecordsQuery Q;
                Q.Object = uint8(ERacingHallObject::Cabinet);
                if (bCard) Q.Subject = TEXT("stable:hidamari");
                St.Seq = Records->Ask(Q);
                return false;
            }
            if (Records->GetPage().Seq != St.Seq) return !TimedOut(10., TEXT("a records page"), Error) && false;
            const FRacingRecordsPage& P = Records->GetPage();
            Check(bCard ? TEXT("records: the guest's stable card") : TEXT("records: the cabinet by wins"), P.Error.IsEmpty() && (P.Lines.Num() > 0 || !P.Title.IsEmpty()),
                FString::Printf(TEXT("'%s' %d lines, %d/%d pages %s"), *P.Title, P.Lines.Num(), P.Page + 1, P.Pages, *P.Error));
            St.Seq = 0;
            if (!bCard) { Go(EStep::RecordsCard); return false; }
            Wallet->SetCounterOpen(true);
            St.CoinsBeforeBets = Wallet->GetView().Coins;
            Go(EStep::Bet);
            return false;
        }
        case EStep::Bet:
        {
            if (!Service) return false;
            const FRacingNetRace& Race = Service->GetNetState().Race;
            const double Now = Service->WorldNow();
            if (Wallet->IsPending()) return !TimedOut(120., TEXT("the bets"), Error) && false;
            if (St.Seq && Wallet->GetReplySeq() == St.Seq)
            {
                Check(FString::Printf(TEXT("bet %d taken"), St.Bets), Wallet->GetReplyError().IsEmpty(), Wallet->GetReplyError());
                St.Seq = 0;
            }
            if (St.RaceKey.IsEmpty())
            {
                // The race in focus, still open to bets for a few seconds, as the card lists it.
                if (Race.Key.IsEmpty() || Race.bRun || Race.Start - Now < 6.) return !TimedOut(120., TEXT("a race open to bets"), Error) && false;
                const FRacingCardRace* Card = Wallet->GetCard().Races.FindByPredicate([&Race](const FRacingCardRace& R) { return R.Key == Race.Key; });
                if (!Card || Card->Runners.Num() < 2) return !TimedOut(120., TEXT("the race card"), Error) && false;
                TArray<FRacingCardRunner> Sorted = Card->Runners;
                Sorted.Sort([](const FRacingCardRunner& A, const FRacingCardRunner& B) { return A.OddsHundredths < B.OddsHundredths; });
                for (int32 I = 0; I < FMath::Min(3, Sorted.Num()); ++I) St.Runners.Add(Sorted[I].HorseId);
                St.RaceKey = Race.Key;
                St.RaceStart = Race.Start;
                St.CoinsBeforeBets = Wallet->GetView().Coins;
                for (const FRacingTicketView& T : Wallet->GetView().Tickets) St.Tickets.Add(T.Id);
                St.Report->SetStringField(TEXT("bet_race"), Race.Key);
                St.Report->SetNumberField(TEXT("coins_before_bets"), St.CoinsBeforeBets);
            }
            if (St.Seq) return false;
            if (St.Bets < St.Runners.Num())
            {
                if (Now >= St.RaceStart - 1.) { Check(TEXT("bets placed before the start"), false); St.Bets = St.Runners.Num(); return false; }
                const uint32 Sent = Wallet->RequestBet(St.RaceKey, St.Runners[St.Bets], 3);
                if (Sent) { St.Seq = Sent; ++St.Bets; }
                return false;
            }
            // The new tickets: those of this race.
            TArray<FString> Mine;
            for (const FRacingTicketView& T : Wallet->GetView().Tickets)
                if (!St.Tickets.Contains(T.Id)) Mine.Add(T.Id);
            if (Mine.Num() < St.Runners.Num()) return !TimedOut(120., TEXT("the tickets in the wallet"), Error) && false;
            St.Tickets = Mine;
            St.Report->SetObjectField(TEXT("wallet_after_bets"), WalletJson(Wallet));
            Check(TEXT("bets: stakes taken from the wallet"), Wallet->GetView().Coins == St.CoinsBeforeBets - 3 * Mine.Num(),
                FString::Printf(TEXT("%d -> %d for %d tickets"), St.CoinsBeforeBets, Wallet->GetView().Coins, Mine.Num()));
            Shot(TEXT("2-bets"));
            Go(EStep::Race);
            return false;
        }
        case EStep::Race:
        {
            int32 Open = 0, Paid = 0, Staked = 0;
            for (const FRacingTicketView& T : Wallet->GetView().Tickets)
                if (St.Tickets.Contains(T.Id))
                {
                    Open += T.GetStatus() == ERacingTicket::Open;
                    Paid += T.Payout;
                    Staked += T.Stake;
                }
            if (Open) return !TimedOut(400., TEXT("the bets settled"), Error) && false;
            St.Report->SetObjectField(TEXT("wallet_settled"), WalletJson(Wallet));
            const int32 Coins = Wallet->GetView().Coins;
            Check(TEXT("bets settled into the wallet"), Coins == St.CoinsBeforeBets - Staked + Paid,
                FString::Printf(TEXT("%d - %d staked + %d paid = %d (wallet %d)"), St.CoinsBeforeBets, Staked, Paid, St.CoinsBeforeBets - Staked + Paid, Coins));
            Check(TEXT("a bet paid out"), Paid > 0, FString::Printf(TEXT("%d coins paid"), Paid));
            Shot(TEXT("3-settled"));
            Wallet->SetCounterOpen(false);
            St.BeforeLeave = MakeShared<FJsonObject>();
            St.BeforeLeave->SetObjectField(TEXT("wallet"), WalletJson(Wallet));
            St.BeforeLeave->SetObjectField(TEXT("stable"), StableJson(Desk));
            St.Report->SetObjectField(TEXT("before_leave"), St.BeforeLeave);
            Go(EStep::Leave);
            return false;
        }
        case EStep::Leave:
            // A moment for the host to note the end of the race, then leave as the menu does.
            if (FPlatformTime::Seconds() - St.StepAt < 3.) return false;
            St.bRejoining = true;
            Session->LeaveGame();
            Go(EStep::Away);
            return false;
        case EStep::Away:
        {
            if (World->GetNetMode() != NM_Standalone || !World->GetFirstPlayerController() || !World->GetFirstPlayerController()->GetPawn())
                return !TimedOut(150., TEXT("the return to Solo"), Error) && false;
            if (FPlatformTime::Seconds() - St.StepAt < 8.) return false;
            Check(TEXT("guest back in Solo"), true);
            Session->JoinGame(St.Address);
            Go(EStep::Rejoin);
            return false;
        }
        case EStep::Rejoin:
        {
            if (!Connected(World)) return !TimedOut(180., TEXT("the guest's return"), Error) && false;
            // The wallet and stable views arrive within the host's next refreshes.
            if (FPlatformTime::Seconds() - St.StepAt < 3.) return false;
            St.bRejoining = false;
            const TSharedPtr<FJsonObject> WalletNow = WalletJson(Wallet), StableNow = StableJson(Desk);
            St.Report->SetObjectField(TEXT("after_rejoin"), MakeShared<FJsonObject>());
            St.Report->GetObjectField(TEXT("after_rejoin"))->SetObjectField(TEXT("wallet"), WalletNow);
            St.Report->GetObjectField(TEXT("after_rejoin"))->SetObjectField(TEXT("stable"), StableNow);
            const TSharedPtr<FJsonObject> WasW = St.BeforeLeave->GetObjectField(TEXT("wallet")), WasS = St.BeforeLeave->GetObjectField(TEXT("stable"));
            auto Ids = [](const TSharedPtr<FJsonObject>& O, const TCHAR* Field, const TCHAR* Key)
            {
                TArray<FString> Out;
                for (const TSharedPtr<FJsonValue>& V : O->GetArrayField(Field))
                    Out.Add(Key ? V->AsObject()->GetStringField(Key) : V->AsString());
                Out.Sort();
                return FString::Join(Out, TEXT(","));
            };
            Check(TEXT("rejoin: the same wallet"), WalletNow->GetNumberField(TEXT("coins")) == WasW->GetNumberField(TEXT("coins")) &&
                !WalletNow->GetBoolField(TEXT("session")), FString::Printf(TEXT("%d coins, before leaving %d"),
                int32(WalletNow->GetNumberField(TEXT("coins"))), int32(WasW->GetNumberField(TEXT("coins")))));
            Check(TEXT("rejoin: the same tickets"), Ids(WalletNow, TEXT("tickets"), TEXT("id")) == Ids(WasW, TEXT("tickets"), TEXT("id")),
                Ids(WalletNow, TEXT("tickets"), TEXT("id")));
            Check(TEXT("rejoin: the same stable"), StableNow->GetStringField(TEXT("site")) == WasS->GetStringField(TEXT("site")) &&
                Ids(StableNow, TEXT("horses"), nullptr) == Ids(WasS, TEXT("horses"), nullptr),
                StableNow->GetStringField(TEXT("site")) + TEXT(": ") + Ids(StableNow, TEXT("horses"), nullptr));
            Shot(TEXT("4-rejoined"));
            Go(EStep::Done);
            return true;
        }
        default:
            return St.Step == EStep::Done;
        }
    }

    APlayerController* RemoteController(UWorld* World)
    {
        for (FConstPlayerControllerIterator It = World->GetPlayerControllerIterator(); It; ++It)
            if (It->Get() && !It->Get()->IsLocalController()) return It->Get();
        return nullptr;
    }

    TSharedPtr<FJsonObject> PlayerJson(const ARacingService* Service, const FString& Key)
    {
        auto O = MakeShared<FJsonObject>();
        O->SetStringField(TEXT("key"), Key);
        if (!Service) return O;
        const FHRWorldState& W = Service->GetWorldState();
        const FHRPlayer* P = HRRules::FindPlayer(W, Key);
        const FHRStable* St = HRRules::PlayerStable(W, Key);
        O->SetBoolField(TEXT("known"), P != nullptr);
        O->SetNumberField(TEXT("coins"), P ? P->Coins : -1);
        O->SetStringField(TEXT("stable"), St ? St->Id : FString());
        int32 Tickets = 0;
        for (const FHRTicket& T : W.Tickets) Tickets += T.PlayerId == Key;
        O->SetNumberField(TEXT("tickets"), Tickets);
        return O;
    }

    bool TickHost(UWorld* World, FString& Error)
    {
        FState& St = S();
        ARacingService* Service = ARacingService::Find(World);
        APlayerController* Guest = RemoteController(World);
        const URacingWallet* GuestWallet = Guest ? URacingWallet::Of(Guest) : nullptr;
        const FString Key = GuestWallet ? GuestWallet->GetGuestKey() : FString();
        switch (St.Step)
        {
        case EStep::Wait:
        case EStep::HostWait:
        {
            if (St.Step == EStep::Wait) Go(EStep::HostWait);
            if (!Service || Key.IsEmpty() || !HRRules::FindPlayer(Service->GetWorldState(), Key))
                return !TimedOut(300., TEXT("the guest's racing identity"), Error) && false;
            St.GuestKey = Key;
            const FString HostKey = ARacingService::PlayerIdOf(World->GetFirstPlayerController());
            St.Report->SetObjectField(TEXT("guest"), PlayerJson(Service, Key));
            St.Report->SetObjectField(TEXT("host"), PlayerJson(Service, HostKey));
            Check(TEXT("guest keyed by its install id"), Key.StartsWith(TEXT("guest:")), Key);
            Check(TEXT("host's player keeps Belmonte"), PlayerJson(Service, HostKey)->GetStringField(TEXT("stable")) == TEXT("old_mill"), HostKey);
            Check(TEXT("guest gets Hidamari"), PlayerJson(Service, Key)->GetStringField(TEXT("stable")) == TEXT("hidamari"));
            // A race soon, for the guest's bets after its stable and records.
            Service->JumpToNextRace(50.);
            Go(EStep::HostRace);
            return false;
        }
        case EStep::HostRace:
            if (Service && FParse::Param(FCommandLine::Get(), TEXT("networkrender")))
            {
                // The host watches the race on the Salon's TV, then films the result.
                const FRacingNetState& Net = Service->GetNetState();
                const double Now = Service->WorldNow();
                ARacingBroadcast* Tv = ARacingBroadcast::Find(World);
                if (!St.bTv && Tv && Now > Net.Race.Start - 20.) St.bTv = Tv->GoToScreen(TEXT("salon_paris"));
                if (St.bTv && !St.bTvShot && Now > Net.Race.Start + 15.) { St.bTvShot = true; Shot(TEXT("1-tv-race")); }
                if (St.bTvShot && !St.bResultShot && !Net.Last.Key.IsEmpty() && Net.Last.Key == Net.Race.Key)
                { St.bResultShot = true; Shot(TEXT("2-tv-result")); }
            }
            if (Guest) return !TimedOut(600., TEXT("the guest leaving"), Error) && false;
            St.Report->SetObjectField(TEXT("guest_left"), PlayerJson(Service, St.GuestKey));
            Check(TEXT("the guest's stable stays theirs while away"), PlayerJson(Service, St.GuestKey)->GetStringField(TEXT("stable")) == TEXT("hidamari"));
            Go(EStep::HostGuestAway);
            return false;
        case EStep::HostGuestAway:
            if (Key.IsEmpty()) return !TimedOut(300., TEXT("the guest's return"), Error) && false;
            St.Report->SetObjectField(TEXT("guest_back"), PlayerJson(Service, Key));
            Check(TEXT("the guest comes back with the same key"), Key == St.GuestKey, Key);
            Check(TEXT("with the same coins"), PlayerJson(Service, Key)->GetNumberField(TEXT("coins")) ==
                St.Report->GetObjectField(TEXT("guest_left"))->GetNumberField(TEXT("coins")));
            Go(EStep::HostGuestBack);
            return false;
        case EStep::HostGuestBack:
            // The guest's own checks take a few seconds; done once it is gone again.
            if (Guest) return !TimedOut(120., TEXT("the guest's final leave"), Error) && false;
            Go(EStep::Done);
            return true;
        default:
            return St.Step == EStep::Done;
        }
    }

    bool Tick(UJapanGameInstance* Session, UWorld* World, bool bServer, const FString& Folder, FString& Error)
    {
        FState& St = S();
        if (!St.bStarted)
        {
            St.bStarted = true;
            St.bServer = bServer;
            St.Folder = Folder;
            St.Report = MakeShared<FJsonObject>();
            St.Step = EStep::Wait;
            St.StepAt = FPlatformTime::Seconds();
            int32 Port = 7777;
            FParse::Value(FCommandLine::Get(), TEXT("port="), Port);
            St.Address = FString::Printf(TEXT("127.0.0.1:%d"), Port);
        }
        if (!World || !World->HasBegunPlay()) return false;
        if (St.Step != EStep::Done) Sample(World);
        const bool bDone = bServer ? TickHost(World, Error) : TickGuest(Session, World, Error);
        if (bDone || !Error.IsEmpty()) Write();
        return bDone;
    }

    bool IsRejoining() { return S().bRejoining; }
}
