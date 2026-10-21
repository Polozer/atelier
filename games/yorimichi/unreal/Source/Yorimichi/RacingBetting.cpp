#include "RacingBetting.h"
#include "BelmonteRegion.h"
#include "HRRules.h"
#include "HRSave.h"
#include "JapanHUD.h"
#include "RacingPlaces.h"
#include "RacingIdentity.h"
#include "RacingService.h"
#include "JapanSession.h"
#include "SkateComponent.h"
#include "WandererCharacter.h"
#include "Dom/JsonObject.h"
#include "Brushes/SlateColorBrush.h"
#include "Brushes/SlateRoundedBoxBrush.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "Input/Events.h"
#include "InputCoreTypes.h"
#include "Net/UnrealNetwork.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/Layout/SSpacer.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

// ------------------------------------------------------------------------------------------------------------ wallet

URacingWallet::URacingWallet()
{
    // It ticks only on a guest, until it has presented its install id (TickComponent).
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
    PrimaryComponentTick.TickInterval = .25f;
    SetIsReplicatedByDefault(true);
}

void URacingWallet::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    const AController* Owner = Cast<AController>(GetOwner());
    // The host and offline games know their own player (RacingIdentity::HostKey): nothing to present.
    if (bIdentitySent || GetNetMode() != NM_Client) { SetComponentTickEnabled(false); return; }
    if (!Owner || !Owner->IsLocalController()) return;
    bIdentitySent = true;
    SetComponentTickEnabled(false);
    const FString Id = ARacingService::LocalInstallId();
    UE_LOG(LogTemp, Display, TEXT("RACING identity presented to the host: %s"), *Id);
    ServerIdentify(Id);
}

void URacingWallet::ServerIdentify_Implementation(const FString& InstallId)
{
    HostIdentify(InstallId);
}

void URacingWallet::HostIdentify(const FString& InstallId)
{
    // Once per connection: a key never changes under a player in a session.
    if (!GuestKey.IsEmpty()) return;
    const AController* Owner = Cast<AController>(GetOwner());
    TSet<FString> Held;
    if (const UWorld* World = GetWorld())
        for (FConstPlayerControllerIterator It = World->GetPlayerControllerIterator(); It; ++It)
            if (It->Get() != Owner)
                if (const URacingWallet* Other = Of(It->Get()); Other && !Other->GuestKey.IsEmpty()) Held.Add(Other->GuestKey);
    const AJapanPlayerState* PS = Owner ? Owner->GetPlayerState<AJapanPlayerState>() : nullptr;
    FString Why;
    GuestKey = RacingIdentity::ResolveGuest(InstallId.Left(64), PS ? PS->SessionPlayerId : FString(), Held, &Why);
    UE_LOG(LogTemp, Display, TEXT("RACING identity: a guest is %s%s%s"), *GuestKey, Why.IsEmpty() ? TEXT("") : TEXT(", this session only: "), *Why);
    // Registered on the service's next pass (at most a second), its wallet and stable views then.
}

void URacingWallet::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
    Super::GetLifetimeReplicatedProps(OutLifetimeProps);
    // A player's coins and tickets are theirs alone; the card is only theirs while their window is open.
    DOREPLIFETIME_CONDITION(URacingWallet, View, COND_OwnerOnly);
    DOREPLIFETIME_CONDITION(URacingWallet, Card, COND_OwnerOnly);
}

URacingWallet* URacingWallet::Of(const AController* Controller)
{
    return Controller ? Controller->FindComponentByClass<URacingWallet>() : nullptr;
}

URacingWallet* URacingWallet::Local(const UObject* WorldContext)
{
    const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
    return World ? Of(World->GetFirstPlayerController()) : nullptr;
}

void URacingWallet::SetCounterOpen(bool bOpen)
{
    const AActor* Owner = GetOwner();
    if (!Owner) return;
    if (Owner->HasAuthority()) ServerSetCounter_Implementation(bOpen);
    else ServerSetCounter(bOpen);
}

void URacingWallet::ServerSetCounter_Implementation(bool bOpen)
{
    bCounterOpen = bOpen;
    if (!bOpen) HostSetCard(FRacingCard());
    else if (ARacingService* Service = ARacingService::Find(this)) Service->RefreshWallets();
}

uint32 URacingWallet::RequestBet(const FString& RaceKey, const FString& HorseId, int32 Stake)
{
    const double Now = FPlatformTime::Seconds();
    // One request at a time; an answer lost with a connection frees the window after a few seconds.
    if (PendingSeq && Now - PendingSince < 5.) return 0;
    const AActor* Owner = GetOwner();
    if (!Owner) return 0;
    FRacingBetRequest Request;
    Request.Seq = NextSeq++;
    Request.RaceKey = RaceKey;
    Request.HorseId = HorseId;
    Request.Stake = Stake;
    PendingSeq = Request.Seq;
    PendingSince = Now;
    if (Owner->HasAuthority()) ApplyReply(Request.Seq, HostHandle(Request, ARacingService::Find(this)));
    else ServerPlaceBet(Request);
    return Request.Seq;
}

void URacingWallet::ServerPlaceBet_Implementation(const FRacingBetRequest& Request)
{
    // A client cannot flood the host: at most five requests a second are looked at.
    const double Now = FPlatformTime::Seconds();
    if (LastRequest >= 0. && Now - LastRequest < .2)
    {
        ClientBetReply(Request.Seq, TEXT("Un instant, le guichet traite votre pari."));
        return;
    }
    LastRequest = Now;
    ClientBetReply(Request.Seq, HostHandle(Request, ARacingService::Find(this)));
}

FString URacingWallet::HostHandle(const FRacingBetRequest& Request, ARacingService* Service)
{
    if (Request.RaceKey.IsEmpty() || Request.HorseId.IsEmpty() || Request.RaceKey.Len() > HRSave::MaxIdChars ||
        Request.HorseId.Len() > HRSave::MaxIdChars)
        return TEXT("Ce pari n'est pas valable.");
    if (!Service || !Service->HasWorld()) return TEXT("Les guichets sont fermés pour le moment.");
    if (HostPlayerId.IsEmpty()) HostPlayerId = ARacingService::PlayerIdOf(Cast<AController>(GetOwner()));
    return Service->PlaceBet(HostPlayerId, Request.RaceKey, Request.HorseId, Request.Stake);
}

void URacingWallet::ClientBetReply_Implementation(uint32 Seq, const FString& Error)
{
    ApplyReply(Seq, Error);
}

void URacingWallet::ApplyReply(uint32 Seq, const FString& Error)
{
    if (Seq == PendingSeq) PendingSeq = 0;
    ReplySeq = Seq;
    ReplyError = Error;
    ++Revision;
}

void URacingWallet::HostSetView(const FRacingWalletView& Next)
{
    if (Next == View) return;
    const FRacingWalletView Before = View;
    View = Next;
    ++Revision;
    // The host's own player hears of its results here; a guest's in OnRep_View.
    const AController* Owner = Cast<AController>(GetOwner());
    if (Owner && Owner->IsLocalController()) Announce(Before, View);
}

void URacingWallet::HostSetCard(const FRacingCard& Next)
{
    if (Next == Card) return;
    Card = Next;
    ++Revision;
}

void URacingWallet::OnRep_View(const FRacingWalletView& Before)
{
    ++Revision;
    Announce(Before, View);
}

void URacingWallet::OnRep_Card()
{
    ++Revision;
}

void URacingWallet::Announce(const FRacingWalletView& Before, const FRacingWalletView& After)
{
    if (!Before.bActive) return;   // the first view of a session is not news
    FString Line;
    for (const FRacingTicketView& T : After.Tickets)
    {
        if (T.GetStatus() == ERacingTicket::Open) continue;
        const FRacingTicketView* Was = Before.Tickets.FindByPredicate([&T](const FRacingTicketView& B) { return B.Id == T.Id; });
        if (!Was || Was->GetStatus() != ERacingTicket::Open) continue;
        FString One;
        switch (T.GetStatus())
        {
            case ERacingTicket::Won: One = FString::Printf(TEXT("Pari gagnant : %s  +%d pièces"), *T.Horse, T.Payout); break;
            case ERacingTicket::Lost: One = FString::Printf(TEXT("Pari perdu : %s  (%d pièces)"), *T.Horse, T.Stake); break;
            default: One = FString::Printf(TEXT("Pari remboursé : %s  +%d pièces"), *T.Horse, T.Payout); break;
        }
        Line += (Line.IsEmpty() ? TEXT("") : TEXT("   ·   ")) + One;
    }
    if (Line.IsEmpty()) return;
    Toast = Line;
    ToastAt = FPlatformTime::Seconds();
    UE_LOG(LogTemp, Display, TEXT("RACING TICKET %s (solde %d)"), *Line, After.Coins);
}

FString URacingWallet::GetToast(float& Alpha) const
{
    const double Age = FPlatformTime::Seconds() - ToastAt;
    constexpr double Show = 7.;
    if (Toast.IsEmpty() || Age < 0. || Age > Show) { Alpha = 0.f; return FString(); }
    Alpha = float(FMath::Min(FMath::Min(Age / .3, (Show - Age) / 1.), 1.));
    return Toast;
}

// ------------------------------------------------------------------------------------------------------------ the window

// A named namespace: in a unity build an anonymous one would leak into later files.
namespace RacingBetUi
{
    FLinearColor Hex(const TCHAR* InHex, float Alpha = 1.f)
    {
        FLinearColor Color = FLinearColor::FromSRGBColor(FColor::FromHex(InHex));
        Color.A = Alpha;
        return Color;
    }

    // The game's menu palette (the character select's): dark forest boards, brushed brass, cream type.
    const FLinearColor Backdrop = Hex(TEXT("07120e"), .66f);
    const FLinearColor BoardOuter = Hex(TEXT("0b1c15"), .97f);
    const FLinearColor BoardInner = Hex(TEXT("0e221a"), .98f);
    const FLinearColor Plaque = Hex(TEXT("102619"), 1.f);
    const FLinearColor PlaqueSelected = Hex(TEXT("1a3a2b"), 1.f);
    const FLinearColor Brass = Hex(TEXT("c9a05a"));
    const FLinearColor BrassSoft = Hex(TEXT("c9a05a"), .48f);
    const FLinearColor BrassFaint = Hex(TEXT("c9a05a"), .22f);
    const FLinearColor Gold = Hex(TEXT("e6c883"));
    const FLinearColor GoldFill = Hex(TEXT("d9ab4e"));
    const FLinearColor GoldEdge = Hex(TEXT("ffe299"));
    const FLinearColor Cream = Hex(TEXT("fff6e5"));
    const FLinearColor Sage = Hex(TEXT("b9cbbf"));
    const FLinearColor Muted = Hex(TEXT("7f9488"));
    const FLinearColor Ink = Hex(TEXT("19140a"));
    const FLinearColor Win = Hex(TEXT("9fd68a"));
    const FLinearColor Loss = Hex(TEXT("e08f7a"));

    TMap<FString, TSharedPtr<FSlateBrush>>& Brushes()
    {
        static TMap<FString, TSharedPtr<FSlateBrush>> Cache;
        return Cache;
    }

    const FSlateBrush* Solid(const FLinearColor& Fill)
    {
        const FString Key = TEXT("solid:") + Fill.ToString();
        if (const TSharedPtr<FSlateBrush>* Found = Brushes().Find(Key)) return Found->Get();
        return Brushes().Add(Key, MakeShared<FSlateColorBrush>(Fill)).Get();
    }

    const FSlateBrush* Rounded(const FLinearColor& Fill, float Radius, const FLinearColor& Outline = FLinearColor::Transparent, float Width = 0.f)
    {
        const FString Key = FString::Printf(TEXT("round:%s:%.1f:%s:%.1f"), *Fill.ToString(), Radius, *Outline.ToString(), Width);
        if (const TSharedPtr<FSlateBrush>* Found = Brushes().Find(Key)) return Found->Get();
        return Brushes().Add(Key, MakeShared<FSlateRoundedBoxBrush>(FSlateColor(Fill), FVector4(Radius, Radius, Radius, Radius), FSlateColor(Outline), Width)).Get();
    }

    const FButtonStyle& FlatButton()
    {
        static FButtonStyle Style = []
        {
            FButtonStyle S = FCoreStyle::Get().GetWidgetStyle<FButtonStyle>("Button");
            const FSlateColorBrush Empty(FLinearColor::Transparent);
            S.SetNormal(Empty).SetHovered(Empty).SetPressed(Empty).SetDisabled(Empty);
            S.SetNormalPadding(FMargin(0)).SetPressedPadding(FMargin(0));
            return S;
        }();
        return Style;
    }

    FSlateFontInfo Font(const char* Weight, int32 Size, int32 Spacing = 0)
    {
        FSlateFontInfo F = FCoreStyle::GetDefaultFontStyle(Weight, Size);
        F.LetterSpacing = Spacing;
        return F;
    }

    TSharedRef<STextBlock> Text(const FString& Value, const FSlateFontInfo& InFont, const FLinearColor& Color)
    {
        return SNew(STextBlock).Text(FText::FromString(Value)).Font(InFont).ColorAndOpacity(Color)
            .ShadowOffset(FVector2D(0.f, 1.f)).ShadowColorAndOpacity(FLinearColor(0.f, 0.f, 0.f, .6f));
    }

    /** "1 000" (French grouping). */
    FString Coins(int64 Value)
    {
        FString Digits = FString::Printf(TEXT("%lld"), FMath::Abs(Value)), Out;
        for (int32 I = 0; I < Digits.Len(); ++I)
        {
            if (I && (Digits.Len() - I) % 3 == 0) Out += TEXT(" ");
            Out += Digits[I];
        }
        return Value < 0 ? TEXT("-") + Out : Out;
    }

    /** Odds in hundredths as "3,40". */
    FString Odds(int32 Hundredths) { return FString::Printf(TEXT("%d,%02d"), Hundredths / 100, Hundredths % 100); }

    FString Countdown(double Seconds)
    {
        Seconds = FMath::Max(0., Seconds);
        if (Seconds < 60.) return FString::Printf(TEXT("%d s"), FMath::CeilToInt(Seconds));
        if (Seconds < 3600.) return FString::Printf(TEXT("%d min %02d"), int32(Seconds / 60.), int32(FMath::Fmod(Seconds, 60.)));
        return FString::Printf(TEXT("%d h %02d"), int32(Seconds / 3600.), int32(FMath::Fmod(Seconds, 3600.) / 60.));
    }

    const TCHAR* Venue(uint8 V) { return ERacingVenue(V) == ERacingVenue::Belmonte ? TEXT("Belmonte") : TEXT("Hidamari"); }

    /** The buttons' names for the pad in use (the HUD's lettering). */
    struct FPadNames { const TCHAR *Accept, *Back, *Prev, *Next; };
    FPadNames PadNames(int32 Style)
    {
        switch (Style)
        {
            case 1: return {TEXT("A"), TEXT("B"), TEXT("LB"), TEXT("RB")};
            case 2: return {TEXT("Croix"), TEXT("Rond"), TEXT("L1"), TEXT("R1")};
            case 3: return {TEXT("B"), TEXT("A"), TEXT("L"), TEXT("R")};
            default: return {TEXT("Bouton bas"), TEXT("Bouton droit"), TEXT("Gâchette haute G"), TEXT("Gâchette haute D")};
        }
    }

    /**
     * The betting window (docs/RACING.md, "Betting"): today's races open to bets on the left, the selected race's runners
     * and their odds on the right, the stake under them, then the player's tickets. Gamepad first: the bumpers change the
     * race, up and down the horse, left and right the stake, the bottom button bets (pressed twice: choose, then confirm),
     * the right button goes back. The keyboard and the mouse work the same rows. It redraws when the wallet or the card
     * changes, never every frame.
     */
    class SRacingBetWindow : public SCompoundWidget
    {
    public:
        SLATE_BEGIN_ARGS(SRacingBetWindow) {}
        SLATE_END_ARGS()

        TWeakObjectPtr<URacingWallet> Wallet;
        TWeakObjectPtr<ARacingService> Service;
        FString RaceKey, HorseId;
        int32 Stake = 5;
        bool bConfirm = false, bPad = false;
        uint32 Seen = MAX_uint32, Submitted = 0;
        FString Message, SubmittedText;
        bool bMessageOk = false;
        float StickCooldown = 0.f;
        bool bStickX = false, bStickY = false;
        int32 PadStyle = 0;
        TSharedPtr<SBox> Body;

        void Construct(const FArguments&, URacingWallet* InWallet, ARacingService* InService)
        {
            Wallet = InWallet;
            Service = InService;
            PadStyle = AJapanHUD::CurrentControllerStyle();
            bPad = PadStyle != 0;
            ChildSlot
            [
                SNew(SOverlay)
                + SOverlay::Slot()[SNew(SBorder).BorderImage(Solid(Backdrop))]
                + SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center).Padding(32.f, 24.f)
                [
                    SNew(SScaleBox).Stretch(EStretch::ScaleToFit).StretchDirection(EStretchDirection::DownOnly)
                    [
                        SNew(SOverlay)
                        + SOverlay::Slot().Padding(FMargin(0.f, 8.f, 0.f, -8.f))[SNew(SBorder).BorderImage(Rounded(FLinearColor(0.f, 0.f, 0.f, .55f), 15.f))]
                        + SOverlay::Slot()
                        [
                            SNew(SBorder).BorderImage(Rounded(BoardOuter, 14.f, Brass, 1.5f)).Padding(5.f)
                            [
                                SNew(SBorder).BorderImage(Rounded(BoardInner, 11.f, BrassFaint, 1.f)).Padding(FMargin(30.f, 24.f))
                                [
                                    SAssignNew(Body, SBox).WidthOverride(1120.f)
                                ]
                            ]
                        ]
                    ]
                ]
            ];
            Rebuild();
        }

        // ------------------------------------------------------------ state
        const FRacingCard* Card() const { return Wallet.IsValid() ? &Wallet->GetCard() : nullptr; }
        const FRacingWalletView* View() const { return Wallet.IsValid() ? &Wallet->GetView() : nullptr; }
        double Now() const { return Service.IsValid() ? Service->WorldNow() : 0.; }

        int32 RaceIndex() const
        {
            const FRacingCard* C = Card();
            if (!C || C->Races.IsEmpty()) return INDEX_NONE;
            const int32 I = C->Races.IndexOfByPredicate([this](const FRacingCardRace& R) { return R.Key == RaceKey; });
            return I == INDEX_NONE ? 0 : I;
        }
        const FRacingCardRace* Race() const { const int32 I = RaceIndex(); return I == INDEX_NONE ? nullptr : &Card()->Races[I]; }
        int32 RunnerIndex() const
        {
            const FRacingCardRace* R = Race();
            if (!R || R->Runners.IsEmpty()) return INDEX_NONE;
            const int32 I = R->Runners.IndexOfByPredicate([this](const FRacingCardRunner& X) { return X.HorseId == HorseId; });
            return I == INDEX_NONE ? 0 : I;
        }
        const FRacingCardRunner* Runner() const { const int32 I = RunnerIndex(); return I == INDEX_NONE ? nullptr : &Race()->Runners[I]; }

        /** The most the player may stake now: the rules' stake limit, the day's limit and the balance. */
        int32 MaxStake() const
        {
            const FRacingWalletView* V = View();
            if (!V) return 0;
            using L = HRRules::FBetLimits;
            return FMath::Max(0, FMath::Min3(L::MaxStake, L::PerDay - V->DayStaked, V->Coins));
        }

        /** Keeps the selection on what still exists (a race leaves the card at its start). */
        void Normalise()
        {
            if (const FRacingCardRace* R = Race())
            {
                // The selected race left the card (it started): never carry a confirmation over to another race or horse.
                if (!RaceKey.IsEmpty() && R->Key != RaceKey)
                {
                    bConfirm = false;
                    HorseId.Reset();
                    Message = TEXT("Départ donné : les paris sur cette course sont fermés.");
                    bMessageOk = false;
                }
                RaceKey = R->Key;
                const FRacingCardRunner* X = Runner();
                if (!X || (!HorseId.IsEmpty() && X->HorseId != HorseId)) bConfirm = false;
                if (X) HorseId = X->HorseId;
            }
            else { RaceKey.Reset(); HorseId.Reset(); bConfirm = false; }
            const int32 Max = MaxStake();
            Stake = Max <= 0 ? 0 : FMath::Clamp(Stake <= 0 ? FMath::Min(5, Max) : Stake, HRRules::FBetLimits::MinStake, Max);
            if (Stake <= 0) bConfirm = false;
        }

        // ------------------------------------------------------------ actions
        void StepRace(int32 Delta)
        {
            const FRacingCard* C = Card();
            if (!C || C->Races.IsEmpty()) return;
            const int32 I = (RaceIndex() + Delta + C->Races.Num()) % C->Races.Num();
            RaceKey = C->Races[I].Key;
            HorseId.Reset();
            bConfirm = false;
            Rebuild();
        }
        void StepRunner(int32 Delta)
        {
            const FRacingCardRace* R = Race();
            if (!R || R->Runners.IsEmpty() || bConfirm) return;
            HorseId = R->Runners[FMath::Clamp(RunnerIndex() + Delta, 0, R->Runners.Num() - 1)].HorseId;
            Rebuild();
        }
        void StepStake(int32 Delta)
        {
            if (bConfirm) return;
            Stake = FMath::Clamp(Stake + Delta, FMath::Min(HRRules::FBetLimits::MinStake, MaxStake()), MaxStake());
            Rebuild();
        }
        void Accept()
        {
            const FRacingCardRace* R = Race();
            const FRacingCardRunner* X = Runner();
            if (!R || !X || !Wallet.IsValid() || Wallet->IsPending()) return;
            if (Stake <= 0)
            {
                Message = MaxStake() <= 0 && View() && View()->DayStaked >= HRRules::FBetLimits::PerDay
                    ? FString::Printf(TEXT("Vous avez misé %d pièces aujourd'hui : c'est le maximum."), HRRules::FBetLimits::PerDay)
                    : FString(TEXT("Solde insuffisant pour parier."));
                bMessageOk = false;
                Rebuild();
                return;
            }
            if (!bConfirm) { bConfirm = true; Message.Reset(); Rebuild(); return; }
            // Copies: on the host the request is answered at once and the card it points into is replaced.
            const FString Key = R->Key, Id = X->HorseId;
            SubmittedText = FString::Printf(TEXT("Pari enregistré : %d pièces gagnant sur %s."), Stake, *X->Horse);
            Submitted = Wallet->RequestBet(Key, Id, Stake);
            bConfirm = false;
            Message = TEXT("Le guichet enregistre votre pari…");
            bMessageOk = true;
            Rebuild();
        }
        bool Back()
        {
            if (bConfirm) { bConfirm = false; Rebuild(); return false; }
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
            if (!Wallet.IsValid()) return;
            if (Submitted && Wallet->GetReplySeq() == Submitted)
            {
                const FString& Error = Wallet->GetReplyError();
                bMessageOk = Error.IsEmpty();
                Message = bMessageOk ? SubmittedText : Error;
                Submitted = 0;
                Seen = MAX_uint32;
            }
            if (Wallet->GetRevision() != Seen) Rebuild();
            if (FSlateApplication::IsInitialized() && !HasUserFocus(0).IsSet() && !HasUserFocusedDescendants(0))
                FSlateApplication::Get().SetUserFocus(0, SharedThis(this), EFocusCause::Navigation);
        }

        virtual FReply OnPreviewKeyDown(const FGeometry&, const FKeyEvent& E) override
        {
            const FKey K = E.GetKey();
            if (K.IsGamepadKey() != bPad) { bPad = K.IsGamepadKey(); Seen = MAX_uint32; }
            if (K == EKeys::Gamepad_LeftShoulder || K == EKeys::PageUp || (K == EKeys::Tab && E.IsShiftDown())) StepRace(-1);
            else if (K == EKeys::Gamepad_RightShoulder || K == EKeys::PageDown || K == EKeys::Tab) StepRace(1);
            else if (K == EKeys::Up || K == EKeys::W || K == EKeys::Gamepad_DPad_Up) StepRunner(-1);
            else if (K == EKeys::Down || K == EKeys::S || K == EKeys::Gamepad_DPad_Down) StepRunner(1);
            else if (K == EKeys::Left || K == EKeys::A || K == EKeys::Gamepad_DPad_Left) StepStake(-1);
            else if (K == EKeys::Right || K == EKeys::D || K == EKeys::Gamepad_DPad_Right) StepStake(1);
            else if (K == EKeys::Enter || K == EKeys::SpaceBar || K == EKeys::Gamepad_FaceButton_Bottom || K == EKeys::Virtual_Gamepad_Accept.GetVirtualKey())
            {
                if (!E.IsRepeat()) Accept();
            }
            else if (K == EKeys::Escape || K == EKeys::BackSpace || K == EKeys::Gamepad_FaceButton_Right || K == EKeys::Virtual_Gamepad_Back.GetVirtualKey() ||
                K == EKeys::Gamepad_Special_Right || K == EKeys::Gamepad_Special_Left)
            {
                if (!E.IsRepeat() && (Back() || K == EKeys::Gamepad_Special_Right || K == EKeys::Gamepad_Special_Left)) RacingCounter::Close();
            }
            return FReply::Handled();
        }
        virtual FReply OnKeyDown(const FGeometry&, const FKeyEvent&) override { return FReply::Handled(); }
        virtual FReply OnKeyUp(const FGeometry&, const FKeyEvent&) override { return FReply::Handled(); }

        virtual FReply OnAnalogValueChanged(const FGeometry&, const FAnalogInputEvent& E) override
        {
            const FKey K = E.GetKey();
            const float V = E.GetAnalogValue();
            auto Latch = [this, V](bool& bLatched, TFunctionRef<void(int32)> Step, int32 Sign)
            {
                if (FMath::Abs(V) < .3f) { bLatched = false; return; }
                if (FMath::Abs(V) > .6f && (!bLatched || StickCooldown <= 0.f))
                {
                    bLatched = true;
                    StickCooldown = .28f;
                    if (!bPad) { bPad = true; Seen = MAX_uint32; }
                    Step(V > 0.f ? Sign : -Sign);
                }
            };
            if (K == EKeys::Gamepad_LeftY) Latch(bStickY, [this](int32 D) { StepRunner(D); }, -1);
            else if (K == EKeys::Gamepad_LeftX) Latch(bStickX, [this](int32 D) { StepStake(D); }, 1);
            else return FReply::Unhandled();
            return FReply::Handled();
        }

        // ------------------------------------------------------------ drawing
        void Rebuild()
        {
            if (!Body.IsValid()) return;
            Seen = Wallet.IsValid() ? Wallet->GetRevision() : 0;
            Normalise();
            Body->SetContent(Build());
        }

        TSharedRef<SWidget> Eyebrow(const FString& Value) const { return Text(Value, Font("Bold", 11, 220), Gold); }

        TSharedRef<SWidget> Rule() const
        {
            return SNew(SBox).HeightOverride(1.f)[SNew(SImage).Image(Solid(BrassSoft))];
        }

        TSharedRef<SWidget> Build()
        {
            const FRacingWalletView* V = View();
            const FRacingCard* C = Card();
            TSharedRef<SVerticalBox> Root = SNew(SVerticalBox);
            // Header: the salon, the race day and the purse.
            const FString Day = C && C->Day ? FString::Printf(TEXT("Journée %d  ·  %s"), C->Day, *C->Event) : FString(TEXT("Le programme arrive…"));
            Root->AddSlot().AutoHeight()
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
                [
                    SNew(SVerticalBox)
                    + SVerticalBox::Slot().AutoHeight()[Eyebrow(TEXT("◆   SALON DES PARIS   ◆"))]
                    + SVerticalBox::Slot().AutoHeight().Padding(0.f, 4.f, 0.f, 0.f)[Text(TEXT("Pari gagnant"), Font("Bold", 30), Cream)]
                    + SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f, 0.f, 0.f)[Text(Day, Font("Regular", 13), Sage)]
                ]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                [
                    SNew(SBorder).BorderImage(Rounded(Plaque, 10.f, BrassSoft, 1.f)).Padding(FMargin(22.f, 12.f))
                    [
                        SNew(SVerticalBox)
                        + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right)[Eyebrow(V && V->bSession ? TEXT("SOLDE · CETTE SESSION") : TEXT("SOLDE"))]
                        + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right)
                            [Text(V && V->bActive ? Coins(V->Coins) + TEXT(" pièces") : FString(TEXT("—")), Font("Bold", 26), Gold)]
                        + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right)
                            [Text(FString::Printf(TEXT("Misé aujourd'hui  %d / %d"), V ? V->DayStaked : 0, HRRules::FBetLimits::PerDay), Font("Regular", 12), Sage)]
                    ]
                ]
            ];
            Root->AddSlot().AutoHeight().Padding(0.f, 16.f)[Rule()];
            Root->AddSlot().AutoHeight()
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().AutoWidth()[SNew(SBox).WidthOverride(350.f)[BuildRaces()]]
                + SHorizontalBox::Slot().AutoWidth().Padding(22.f, 0.f)[SNew(SBox).WidthOverride(1.f)[SNew(SImage).Image(Solid(BrassFaint))]]
                + SHorizontalBox::Slot().FillWidth(1.f)[BuildRunners()]
            ];
            Root->AddSlot().AutoHeight().Padding(0.f, 16.f)[Rule()];
            Root->AddSlot().AutoHeight()[BuildTickets()];
            // The legend, in the pad's words or the keyboard's.
            const FPadNames Pad = PadNames(PadStyle == 0 ? 1 : PadStyle);
            const FString Legend = bPad
                ? FString::Printf(TEXT("%s / %s  Course      ·      Haut / Bas  Cheval      ·      Gauche / Droite  Mise      ·      %s  %s      ·      %s  %s"),
                    Pad.Prev, Pad.Next, Pad.Accept, bConfirm ? TEXT("Confirmer") : TEXT("Parier"), Pad.Back, bConfirm ? TEXT("Annuler") : TEXT("Fermer"))
                : FString::Printf(TEXT("Tab  Course      ·      ↑ / ↓  Cheval      ·      ← / →  Mise      ·      Entrée  %s      ·      Échap  %s"),
                    bConfirm ? TEXT("Confirmer") : TEXT("Parier"), bConfirm ? TEXT("Annuler") : TEXT("Fermer"));
            Root->AddSlot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 18.f, 0.f, 0.f)
            [
                SNew(SBorder).BorderImage(Rounded(BoardOuter, 10.f, BrassSoft, 1.f)).Padding(FMargin(26.f, 9.f))
                [Text(Legend, Font("Regular", 13), Hex(TEXT("f3e8d2")))]
            ];
            return Root;
        }

        /** Tomorrow's meeting, read-only: "Demain : Hippodrome de Belmonte · 5 courses · 1re dans 1 h 05". */
        void AddPreview(TSharedRef<SVerticalBox> List)
        {
            const FRacingCard* C = Card();
            if (!C || !C->Next.Day) return;
            const FRacingCardPreview& N = C->Next;
            TWeakPtr<SRacingBetWindow> Self = SharedThis(this);
            const double First = N.FirstStart;
            List->AddSlot().AutoHeight().Padding(0.f, 14.f, 0.f, 8.f)[Eyebrow(TEXT("DEMAIN  ·  PROGRAMME"))];
            List->AddSlot().AutoHeight()
            [
                SNew(SBorder).BorderImage(Rounded(Hex(TEXT("0c1d15")), 8.f, BrassFaint, 1.f)).Padding(FMargin(14.f, 9.f))
                [
                    SNew(SVerticalBox)
                    + SVerticalBox::Slot().AutoHeight()[Text(FString::Printf(TEXT("Hippodrome de %s"), Venue(N.Venue)), Font("Bold", 14), Sage)]
                    + SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f, 0.f, 0.f)
                        [SNew(STextBlock).AutoWrapText(true).Font(Font("Regular", 11)).ColorAndOpacity(Muted)
                            .Text(FText::FromString(FString::Printf(TEXT("%s%s"), *N.Event, N.bGrandPrix ? TEXT("  (Grand Prix)") : TEXT(""))))]
                    + SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f, 0.f, 0.f)
                    [
                        SNew(STextBlock).Font(Font("Regular", 11)).ColorAndOpacity(Sage)
                        .Text_Lambda([Self, First, Races = N.Races, Distance = N.Distance]
                        {
                            auto W = Self.Pin();
                            return FText::FromString(FString::Printf(TEXT("%d course%s  ·  %d m  ·  1re dans %s"), Races, Races > 1 ? TEXT("s") : TEXT(""),
                                Distance, W ? *Countdown(First - W->Now()) : TEXT("")));
                        })
                    ]
                    + SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f, 0.f, 0.f)[Text(TEXT("Paris ouverts le jour même."), Font("Regular", 11), Muted)]
                ]
            ];
        }

        TSharedRef<SWidget> BuildRaces()
        {
            TSharedRef<SVerticalBox> List = SNew(SVerticalBox);
            List->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 10.f)[Eyebrow(TEXT("COURSES OUVERTES"))];
            const FRacingCard* C = Card();
            if (!C || C->Races.IsEmpty())
            {
                TWeakPtr<SRacingBetWindow> Self = SharedThis(this);
                List->AddSlot().AutoHeight()
                [
                    SNew(STextBlock).AutoWrapText(true).Font(Font("Regular", 13)).ColorAndOpacity(Sage)
                    .Text_Lambda([Self]
                    {
                        const TSharedPtr<SRacingBetWindow> W = Self.Pin();
                        const FRacingCard* Card = W ? W->Card() : nullptr;
                        if (!Card || !Card->Day) return FText::FromString(TEXT("Le guichetier prépare le programme…"));
                        return FText::FromString(FString::Printf(TEXT("Plus de course ouverte aujourd'hui.\nProchaine réunion dans %s."),
                            *Countdown(Card->NextMeeting - W->Now())));
                    })
                ];
                AddPreview(List);
                return List;
            }
            const int32 Selected = RaceIndex();
            for (int32 I = 0; I < C->Races.Num(); ++I)
            {
                const FRacingCardRace& R = C->Races[I];
                const bool bSel = I == Selected;
                const double Start = R.Start;
                TWeakPtr<SRacingBetWindow> Self = SharedThis(this);
                const FString Key = R.Key;
                List->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 6.f)
                [
                    SNew(SButton).ButtonStyle(&FlatButton()).ContentPadding(0)
                    .OnClicked_Lambda([Self, Key] { if (auto W = Self.Pin()) { W->RaceKey = Key; W->HorseId.Reset(); W->bConfirm = false; W->Rebuild(); } return FReply::Handled(); })
                    [
                        SNew(SBorder).BorderImage(Rounded(bSel ? PlaqueSelected : Plaque, 8.f, bSel ? Brass : BrassFaint, bSel ? 1.5f : 1.f))
                        .Padding(FMargin(14.f, 9.f))
                        [
                            SNew(SVerticalBox)
                            + SVerticalBox::Slot().AutoHeight()
                            [
                                SNew(SHorizontalBox)
                                + SHorizontalBox::Slot().FillWidth(1.f)[Text(R.Name, Font("Bold", 14), bSel ? Cream : Sage)]
                                + SHorizontalBox::Slot().AutoWidth().Padding(8.f, 0.f, 0.f, 0.f)
                                [
                                    SNew(STextBlock).Font(Font("Bold", 13)).ColorAndOpacity(bSel ? Gold : BrassSoft)
                                    .Text_Lambda([Self, Start] { auto W = Self.Pin(); return FText::FromString(W ? Countdown(Start - W->Now()) : FString()); })
                                ]
                            ]
                            + SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f, 0.f, 0.f)
                            [
                                Text(FString::Printf(TEXT("Hippodrome de %s  ·  %d m%s"), Venue(R.Venue), R.Distance,
                                    R.MyTickets ? *FString::Printf(TEXT("  ·  %d ticket%s"), R.MyTickets, R.MyTickets > 1 ? TEXT("s") : TEXT("")) : TEXT("")),
                                    Font("Regular", 11), Muted)
                            ]
                        ]
                    ]
                ];
            }
            AddPreview(List);
            return List;
        }

        TSharedRef<SWidget> BuildRunners()
        {
            TSharedRef<SVerticalBox> Col = SNew(SVerticalBox);
            const FRacingCardRace* R = Race();
            if (!R)
            {
                Col->AddSlot().AutoHeight()[Eyebrow(TEXT("PARTANTS"))];
                Col->AddSlot().AutoHeight().Padding(0.f, 12.f)[Text(TEXT("Aucune course n'est ouverte aux paris pour le moment."), Font("Regular", 14), Sage)];
                return Col;
            }
            TWeakPtr<SRacingBetWindow> Self = SharedThis(this);
            const double Start = R->Start;
            Col->AddSlot().AutoHeight()[Text(R->Name, Font("Bold", 20), Cream)];
            Col->AddSlot().AutoHeight().Padding(0.f, 2.f, 0.f, 12.f)
            [
                SNew(STextBlock).Font(Font("Regular", 13)).ColorAndOpacity(Sage)
                .Text_Lambda([Self, Start, Where = FString(Venue(R->Venue)), Distance = R->Distance]
                {
                    auto W = Self.Pin();
                    return FText::FromString(FString::Printf(TEXT("Hippodrome de %s  ·  %d m  ·  départ dans %s  ·  paris fermés au départ"), *Where, Distance,
                        W ? *Countdown(Start - W->Now()) : TEXT("")));
                })
            ];
            Col->AddSlot().AutoHeight().Padding(14.f, 0.f, 14.f, 6.f)
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().FillWidth(1.f)[Eyebrow(TEXT("CHEVAL  ·  JOCKEY  ·  ÉCURIE"))]
                + SHorizontalBox::Slot().AutoWidth()[Eyebrow(TEXT("COTE"))]
            ];
            const int32 Selected = RunnerIndex();
            for (int32 I = 0; I < R->Runners.Num(); ++I)
            {
                const FRacingCardRunner& X = R->Runners[I];
                const bool bSel = I == Selected;
                const FString Id = X.HorseId;
                Col->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 5.f)
                [
                    SNew(SButton).ButtonStyle(&FlatButton()).ContentPadding(0)
                    .OnClicked_Lambda([Self, Id]
                    {
                        if (auto W = Self.Pin())
                        {
                            if (W->HorseId == Id && !W->bConfirm) W->Accept();
                            else if (!W->bConfirm) { W->HorseId = Id; W->Rebuild(); }
                        }
                        return FReply::Handled();
                    })
                    [
                        SNew(SBorder).BorderImage(Rounded(bSel ? PlaqueSelected : Plaque, 8.f, bSel ? Brass : BrassFaint, bSel ? 1.5f : 1.f))
                        .Padding(FMargin(14.f, 8.f))
                        [
                            SNew(SHorizontalBox)
                            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 14.f, 0.f)
                            [
                                SNew(SBox).WidthOverride(22.f).HeightOverride(22.f)
                                [SNew(SBorder).BorderImage(Rounded(FLinearColor::FromSRGBColor(X.Silks), 5.f, Cream.CopyWithNewOpacity(.55f), 1.f))]
                            ]
                            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 12.f, 0.f)
                            [Text(FString::Printf(TEXT("%d"), I + 1), Font("Bold", 13), Muted)]
                            + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
                            [
                                SNew(SVerticalBox)
                                + SVerticalBox::Slot().AutoHeight()[Text(X.Horse, Font("Bold", 16), bSel ? Cream : Sage)]
                                + SVerticalBox::Slot().AutoHeight()
                                    [Text(FString::Printf(TEXT("%s  ·  %s"), X.Jockey.IsEmpty() ? TEXT("Jockey de l'écurie") : *X.Jockey, *X.Stable), Font("Regular", 11), Muted)]
                            ]
                            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(10.f, 0.f)
                            [
                                X.Mine
                                    ? StaticCastSharedRef<SWidget>(SNew(SBorder).BorderImage(Rounded(BrassFaint, 6.f)).Padding(FMargin(8.f, 2.f))
                                        [Text(FString::Printf(TEXT("%d ticket%s"), X.Mine, X.Mine > 1 ? TEXT("s") : TEXT("")), Font("Bold", 10), Gold)])
                                    : StaticCastSharedRef<SWidget>(SNew(SSpacer))
                            ]
                            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                            [SNew(SBox).MinDesiredWidth(76.f).HAlign(HAlign_Right)[Text(Odds(X.OddsHundredths), Font("Bold", 22), bSel ? Gold : BrassSoft)]]
                        ]
                    ]
                ];
            }
            Col->AddSlot().AutoHeight().Padding(0.f, 10.f, 0.f, 0.f)[BuildStake()];
            if (!Message.IsEmpty())
                Col->AddSlot().AutoHeight().Padding(2.f, 10.f, 0.f, 0.f)[Text(Message, Font("Bold", 13), bMessageOk ? Win : Loss)];
            return Col;
        }

        TSharedRef<SWidget> BuildStake()
        {
            const FRacingCardRunner* X = Runner();
            const int32 Gain = X ? int32(FMath::FloorToInt64(int64(Stake) * X->OddsHundredths / 100.)) : 0;
            TWeakPtr<SRacingBetWindow> Self = SharedThis(this);
            const bool bCan = Stake > 0 && X && Wallet.IsValid() && !Wallet->IsPending();
            if (bConfirm && X)
            {
                return SNew(SBorder).BorderImage(Rounded(Hex(TEXT("2a2414")), 10.f, Gold, 1.5f)).Padding(FMargin(18.f, 12.f))
                [
                    SNew(SHorizontalBox)
                    + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
                    [
                        SNew(SVerticalBox)
                        + SVerticalBox::Slot().AutoHeight()[Eyebrow(TEXT("CONFIRMER LE PARI"))]
                        + SVerticalBox::Slot().AutoHeight().Padding(0.f, 4.f, 0.f, 0.f)
                            [Text(FString::Printf(TEXT("%d pièces gagnant sur %s, cote %s"), Stake, *X->Horse, *Odds(X->OddsHundredths)), Font("Bold", 16), Cream)]
                        + SVerticalBox::Slot().AutoHeight()
                            [Text(FString::Printf(TEXT("Rapporte environ %d pièces s'il gagne : la cote se fixe au départ."), Gain), Font("Regular", 11), Sage)]
                    ]
                    + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(12.f, 0.f, 8.f, 0.f)
                    [ActionButton(TEXT("Annuler"), false, [Self] { if (auto W = Self.Pin()) W->Back(); })]
                    + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                    [ActionButton(TEXT("Confirmer"), true, [Self] { if (auto W = Self.Pin()) W->Accept(); })]
                ];
            }
            return SNew(SBorder).BorderImage(Rounded(Plaque, 10.f, BrassSoft, 1.f)).Padding(FMargin(18.f, 10.f))
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 16.f, 0.f)[Eyebrow(TEXT("MISE"))]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ActionButton(TEXT("◀"), false, [Self] { if (auto W = Self.Pin()) W->StepStake(-1); })]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(10.f, 0.f)
                    [SNew(SBox).MinDesiredWidth(56.f).HAlign(HAlign_Center)[Text(FString::Printf(TEXT("%d"), Stake), Font("Bold", 24), Stake > 0 ? Gold : Muted)]]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ActionButton(TEXT("▶"), false, [Self] { if (auto W = Self.Pin()) W->StepStake(1); })]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(10.f, 0.f, 0.f, 0.f)
                    [Text(FString::Printf(TEXT("pièces  (%d à %d)"), HRRules::FBetLimits::MinStake, HRRules::FBetLimits::MaxStake), Font("Regular", 12), Muted)]
                + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center).HAlign(HAlign_Right).Padding(12.f, 0.f)
                    [Text(X && Stake > 0 ? FString::Printf(TEXT("Gain si victoire ≈ %d"), Gain) : FString(), Font("Regular", 13), Sage)]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                    [ActionButton(TEXT("Parier"), bCan, [Self] { if (auto W = Self.Pin()) W->Accept(); })]
            ];
        }

        TSharedRef<SWidget> ActionButton(const FString& Label, bool bPrimary, TFunction<void()> OnClick) const
        {
            return SNew(SButton).ButtonStyle(&FlatButton()).ContentPadding(0)
                .OnClicked_Lambda([OnClick] { OnClick(); return FReply::Handled(); })
                [
                    SNew(SBorder).BorderImage(bPrimary ? Rounded(GoldFill, 7.f, GoldEdge, 1.f) : Rounded(Hex(TEXT("0a1812"), .95f), 7.f, BrassSoft, 1.f))
                    .Padding(FMargin(16.f, 7.f))
                    [SNew(STextBlock).Text(FText::FromString(Label)).Font(Font("Bold", 13)).ColorAndOpacity(bPrimary ? Ink : Cream)]
                ];
        }

        TSharedRef<SWidget> BuildTickets()
        {
            const FRacingWalletView* V = View();
            TSharedRef<SVerticalBox> Box = SNew(SVerticalBox);
            const int32 Open = V ? V->OpenCount() : 0;
            Box->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 10.f)
                [Eyebrow(FString::Printf(TEXT("MES PARIS  ·  %d EN COURS"), Open))];
            if (!V || V->Tickets.IsEmpty())
            {
                Box->AddSlot().AutoHeight()[Text(TEXT("Aucun pari pour le moment. Choisissez une course, un cheval et votre mise."), Font("Regular", 13), Muted)];
                return Box;
            }
            TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
            for (int32 I = 0; I < FMath::Min(V->Tickets.Num(), 5); ++I)
            {
                const FRacingTicketView& T = V->Tickets[I];
                FString Result;
                FLinearColor Color = Gold;
                switch (T.GetStatus())
                {
                    case ERacingTicket::Won: Result = FString::Printf(TEXT("Gagné  +%d"), T.Payout); Color = Win; break;
                    case ERacingTicket::Lost: Result = TEXT("Perdu"); Color = Loss; break;
                    case ERacingTicket::Refunded: Result = FString::Printf(TEXT("Remboursé  +%d"), T.Payout); Color = Sage; break;
                    default: Result = FString::Printf(TEXT("En cours  ·  cote %s"), *Odds(T.OddsHundredths)); break;
                }
                Row->AddSlot().FillWidth(1.f).Padding(I ? 8.f : 0.f, 0.f, 0.f, 0.f)
                [
                    SNew(SBorder).BorderImage(Rounded(Plaque, 8.f, T.GetStatus() == ERacingTicket::Open ? BrassSoft : BrassFaint, 1.f)).Padding(FMargin(12.f, 8.f))
                    [
                        SNew(SVerticalBox)
                        + SVerticalBox::Slot().AutoHeight()[Text(FString::Printf(TEXT("%s  ·  %d"), *T.Horse, T.Stake), Font("Bold", 13), Cream)]
                        + SVerticalBox::Slot().AutoHeight()[Text(T.Race, Font("Regular", 10), Muted)]
                        + SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f, 0.f, 0.f)[Text(Result, Font("Bold", 12), Color)]
                    ]
                ];
            }
            Box->AddSlot().AutoHeight()[Row];
            return Box;
        }

        FString Json() const
        {
            const FRacingCardRace* R = Race();
            const FRacingCardRunner* X = Runner();
            return FString::Printf(TEXT("{\"race\":\"%s\",\"horse\":\"%s\",\"horse_name\":\"%s\",\"stake\":%d,\"max_stake\":%d,\"confirm\":%s,\"pad\":%s,\"message\":\"%s\"}"),
                R ? *RacingJsonEscape(R->Key) : TEXT(""), X ? *RacingJsonEscape(X->HorseId) : TEXT(""),
                X ? *RacingJsonEscape(X->Horse) : TEXT(""), Stake, MaxStake(), bConfirm ? TEXT("true") : TEXT("false"),
                bPad ? TEXT("true") : TEXT("false"), *RacingJsonEscape(Message));
        }
    };

    struct FOpen
    {
        TSharedPtr<SRacingBetWindow> Window;
        TWeakObjectPtr<AWandererCharacter> Player;
        TWeakObjectPtr<URacingWallet> Wallet;
    };
    FOpen& Open()
    {
        static FOpen State;
        return State;
    }
}

// ------------------------------------------------------------------------------------------------------------ the counter

bool RacingCounter::Parse(const TSharedPtr<FJsonObject>& Places, FCounter& Out)
{
    const TSharedPtr<FJsonObject>* C = nullptr;
    if (!Places || !Places->TryGetObjectField(TEXT("counter"), C) || !C) return false;
    FCounter R;
    double Yaw = 0.;
    if (!RacingPlaces::Vector(*C, TEXT("at_cm"), R.Spot) || !RacingPlaces::Number(*C, TEXT("yaw"), Yaw) ||
        !RacingPlaces::Number(*C, TEXT("half_length_cm"), R.HalfLength) || !RacingPlaces::Number(*C, TEXT("reach_cm"), R.Reach) ||
        !RacingPlaces::Number(*C, TEXT("behind_cm"), R.Behind) || !RacingPlaces::Number(*C, TEXT("below_cm"), R.Below) ||
        !RacingPlaces::Number(*C, TEXT("above_cm"), R.Above))
        return false;
    if (R.HalfLength <= 0. || R.Reach <= 0. || R.Behind <= 0. || R.Below <= 0. || R.Above <= 0.) return false;
    R.Yaw = float(Yaw);
    Out = R;
    return true;
}

const RacingCounter::FCounter* RacingCounter::Get()
{
    static FCounter Counter;
    static int32 State = -1;
    if (State < 0)
    {
        State = Parse(RacingPlaces::Belmonte(), Counter) ? 1 : 0;
        if (!State) UE_LOG(LogTemp, Warning, TEXT("RACING COUNTER no valid racing_places.counter in belmonte/runtime.json: no betting windows"));
    }
    return State ? &Counter : nullptr;
}

bool RacingCounter::InReach(const FVector& Location, const FVector& OriginCm, const FCounter& Counter)
{
    // In the counter's frame: +X towards the windows, +Y along the counter.
    const FVector L = FRotator(0.f, Counter.Yaw, 0.f).UnrotateVector(Location - OriginCm - Counter.Spot);
    return L.X >= -Counter.Reach && L.X <= Counter.Behind && FMath::Abs(L.Y) <= Counter.HalfLength && L.Z >= -Counter.Below &&
        L.Z <= Counter.Above;
}

bool RacingCounter::RegionOrigin(const UObject* WorldContext, FVector& OutCm)
{
    static TWeakObjectPtr<ABelmonteRegion> Cached;
    UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
    if (!World) return false;
    if (!Cached.IsValid() || Cached->GetWorld() != World)
    {
        TActorIterator<ABelmonteRegion> It(World);
        Cached = It ? *It : nullptr;
    }
    if (!Cached.IsValid()) return false;
    OutCm = Cached->GetActorLocation();
    return true;
}

bool RacingCounter::CanUse(const AWandererCharacter* Pawn)
{
    if (!Pawn || !Pawn->IsLocallyControlled() || !Pawn->IsReady() || Pawn->IsMenuOpen() || IsOpen() || Pawn->OnVehicle() ||
        Pawn->IsZeppelinPassenger() || (Pawn->GetSkate() && Pawn->GetSkate()->IsRiding()))
        return false;
    FVector Origin;
    const FCounter* Counter = Get();
    return Counter && URacingWallet::Of(Pawn->GetController()) && RegionOrigin(Pawn, Origin) && InReach(Pawn->GetActorLocation(), Origin, *Counter);
}

bool RacingCounter::TryOpen(AWandererCharacter* Pawn)
{
    if (!CanUse(Pawn) || !GEngine || !GEngine->GameViewport) return false;
    URacingWallet* Wallet = URacingWallet::Of(Pawn->GetController());
    ARacingService* Service = ARacingService::Find(Pawn);
    if (!Wallet || !Service) return false;
    RacingBetUi::FOpen& State = RacingBetUi::Open();
    Wallet->SetCounterOpen(true);
    State.Window = SNew(RacingBetUi::SRacingBetWindow, Wallet, Service);
    State.Player = Pawn;
    State.Wallet = Wallet;
    GEngine->GameViewport->AddViewportWidgetContent(State.Window.ToSharedRef(), 22);
    Pawn->SetMenuOpen(true);
    FSlateApplication::Get().SetUserFocus(0, State.Window, EFocusCause::SetDirectly);
    UE_LOG(LogTemp, Display, TEXT("RACING COUNTER open (%s)"), *Wallet->HostPlayerId);
    return true;
}

bool RacingCounter::IsOpen()
{
    return RacingBetUi::Open().Window.IsValid();
}

void RacingCounter::Close()
{
    RacingBetUi::FOpen& State = RacingBetUi::Open();
    if (!State.Window.IsValid()) return;
    if (GEngine && GEngine->GameViewport) GEngine->GameViewport->RemoveViewportWidgetContent(State.Window.ToSharedRef());
    State.Window.Reset();
    if (URacingWallet* Wallet = State.Wallet.Get()) Wallet->SetCounterOpen(false);
    if (AWandererCharacter* Pawn = State.Player.Get()) Pawn->SetMenuOpen(false);
    State.Player.Reset();
    State.Wallet.Reset();
    UE_LOG(LogTemp, Display, TEXT("RACING COUNTER closed"));
}

FString RacingCounter::WindowJson()
{
    const RacingBetUi::FOpen& State = RacingBetUi::Open();
    return State.Window.IsValid() ? State.Window->Json() : FString(TEXT("null"));
}

bool RacingCounter::GoTo(AWandererCharacter* Pawn)
{
    FVector Origin;
    const FCounter* Counter = Get();
    if (!Pawn || !Counter || !RegionOrigin(Pawn, Origin)) return false;
    // A step back from the central window, facing it.
    const FVector At = Origin + Counter->Spot - FRotator(0.f, Counter->Yaw, 0.f).RotateVector(FVector(70., 0., 0.));
    return Pawn->TravelTo(At, Counter->Yaw, TEXT("salon des paris"), 150.f);
}
