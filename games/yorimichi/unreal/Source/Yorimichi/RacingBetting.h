#pragma once
#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "RacingBetting.generated.h"

class AController;
class FJsonObject;
class ARacingService;
class AWandererCharacter;

/** How a ticket stands, as the player sees it (a decided race shows Open until its winner is home). */
enum class ERacingTicket : uint8 { Open, Won, Lost, Refunded };

/** One of the player's win bets (docs/RACING.md, "Betting"). */
USTRUCT()
struct FRacingTicketView
{
    GENERATED_BODY()
    UPROPERTY() FString Id;
    /** French race name ("Lantern Sprint · course 2") and the horse backed. */
    UPROPERTY() FString Race;
    UPROPERTY() FString Horse;
    UPROPERTY() uint8 Venue = 0;
    UPROPERTY() int32 Day = 0;
    /** World second of the race's start (0 for an earlier day's race). */
    UPROPERTY() double Start = 0.;
    UPROPERTY() int32 Stake = 0;
    /** ERacingTicket. */
    UPROPERTY() uint8 Status = 0;
    /** Coins paid back (a win or a refund), 0 otherwise or while open. */
    UPROPERTY() int32 Payout = 0;
    /** Odds paid (won) or the current odds (open), in hundredths. */
    UPROPERTY() int32 OddsHundredths = 0;

    ERacingTicket GetStatus() const { return ERacingTicket(Status); }
    bool operator==(const FRacingTicketView& O) const
    {
        return Id == O.Id && Race == O.Race && Horse == O.Horse && Venue == O.Venue && Day == O.Day && Start == O.Start &&
            Stake == O.Stake && Status == O.Status && Payout == O.Payout && OddsHundredths == O.OddsHundredths;
    }
};

/** The player's wallet and tickets: replicated to its owner only. */
USTRUCT()
struct FRacingWalletView
{
    GENERATED_BODY()
    /** The player has a record in the racing world (a wallet). */
    UPROPERTY() bool bActive = false;
    /** A guest without a persistent identity: the wallet lasts this session only (docs/RACING.md, "Players"). */
    UPROPERTY() bool bSession = false;
    UPROPERTY() int32 Coins = 0;
    /** Coins staked today (the rules allow HRRules::FBetLimits::PerDay). */
    UPROPERTY() int32 DayStaked = 0;
    UPROPERTY() int32 Day = 0;
    /** Open tickets (soonest race first), then the latest results (newest first, at most MaxResults). */
    UPROPERTY() TArray<FRacingTicketView> Tickets;

    static constexpr int32 MaxResults = 8;
    int32 OpenCount() const;
    bool operator==(const FRacingWalletView& O) const
    {
        return bActive == O.bActive && bSession == O.bSession && Coins == O.Coins && DayStaked == O.DayStaked && Day == O.Day &&
            Tickets == O.Tickets;
    }
};

USTRUCT()
struct FRacingCardRunner
{
    GENERATED_BODY()
    UPROPERTY() FString HorseId;
    UPROPERTY() FString Horse;
    UPROPERTY() FString Stable;
    UPROPERTY() FString Jockey;
    UPROPERTY() FColor Silks = FColor::White;
    /** Current win odds for one coin, in hundredths (the pool moves as players bet). */
    UPROPERTY() int32 OddsHundredths = 0;
    /** The player's tickets on this horse in this race. */
    UPROPERTY() uint8 Mine = 0;

    bool operator==(const FRacingCardRunner& O) const
    {
        return HorseId == O.HorseId && Horse == O.Horse && Stable == O.Stable && Jockey == O.Jockey && Silks == O.Silks &&
            OddsHundredths == O.OddsHundredths && Mine == O.Mine;
    }
};

/** A race still open to bets. */
USTRUCT()
struct FRacingCardRace
{
    GENERATED_BODY()
    UPROPERTY() FString Key;
    UPROPERTY() FString Name;
    UPROPERTY() uint8 Venue = 0;
    UPROPERTY() int32 Distance = 0;
    UPROPERTY() double Start = 0.;
    /** The player's tickets on this race (the rules allow HRRules::FBetLimits::TicketsPerRace). */
    UPROPERTY() uint8 MyTickets = 0;
    UPROPERTY() TArray<FRacingCardRunner> Runners;

    bool operator==(const FRacingCardRace& O) const
    {
        return Key == O.Key && Name == O.Name && Venue == O.Venue && Distance == O.Distance && Start == O.Start &&
            MyTickets == O.MyTickets && Runners == O.Runners;
    }
};

/** The next race day, read-only (bets open on the day itself): its venue, event and races as the rules plan them. */
USTRUCT()
struct FRacingCardPreview
{
    GENERATED_BODY()
    /** 0 when there is no preview. */
    UPROPERTY() int32 Day = 0;
    UPROPERTY() FString Event;
    UPROPERTY() uint8 Venue = 0;
    UPROPERTY() bool bGrandPrix = false;
    /** Races declared for the day (a Grand Prix final comes later, once its heats are run). */
    UPROPERTY() int32 Races = 0;
    UPROPERTY() int32 Distance = 0;
    /** World second of its first race. */
    UPROPERTY() double FirstStart = 0.;

    bool operator==(const FRacingCardPreview& O) const
    {
        return Day == O.Day && Event == O.Event && Venue == O.Venue && bGrandPrix == O.bGrandPrix && Races == O.Races &&
            Distance == O.Distance && FirstStart == O.FirstStart;
    }
};

/** The betting window's race card: today's races still open to bets. Sent only while the player's counter is open. */
USTRUCT()
struct FRacingCard
{
    GENERATED_BODY()
    UPROPERTY() int32 Day = 0;
    UPROPERTY() FString Event;
    /** World second of the next race day's first race. */
    UPROPERTY() double NextMeeting = 0.;
    UPROPERTY() TArray<FRacingCardRace> Races;
    UPROPERTY() FRacingCardPreview Next;

    bool operator==(const FRacingCard& O) const
    {
        return Day == O.Day && Event == O.Event && NextMeeting == O.NextMeeting && Races == O.Races && Next == O.Next;
    }
};

/** A bet request as it crosses the wire (client to host), and the host's answer. */
USTRUCT()
struct FRacingBetRequest
{
    GENERATED_BODY()
    UPROPERTY() uint32 Seq = 0;
    UPROPERTY() FString RaceKey;
    UPROPERTY() FString HorseId;
    UPROPERTY() int32 Stake = 0;
};

/**
 * The Salon des Paris's betting windows in Belmonte (docs/RACING.md, "Betting"): where the player stands to bet, derived
 * from the Salon hall's committed placement (world/regions/belmonte/build.py SALON_COUNTER, runtime.json
 * 'racing_places.counter'), in Belmonte-local Unreal cm round the region origin, as the TVs. No hardcoded fallback.
 */
namespace RacingCounter
{
    struct FCounter
    {
        /** The player's spot at the central window (GUICHET 2), facing the counter along Yaw. */
        FVector Spot = FVector::ZeroVector;
        float Yaw = 0.f;
        /** The windows span HalfLength either side of the spot along the counter; the player stands within Reach of it
         *  (in front), Behind (towards the counter), Below and Above. */
        double HalfLength = 0., Reach = 0., Behind = 0., Below = 0., Above = 0.;
    };
    /** The counter from runtime.json's 'racing_places' object; false when absent or invalid (non-finite, extents <= 0). */
    YORIMICHI_API bool Parse(const TSharedPtr<FJsonObject>& Places, FCounter& Out);
    /** The staged Belmonte counter (RacingPlaces::Belmonte), parsed once; nullptr when unavailable. */
    YORIMICHI_API const FCounter* Get();
    /** Whether a pawn at Location (world cm) stands at Counter in a region at OriginCm. */
    YORIMICHI_API bool InReach(const FVector& Location, const FVector& OriginCm, const FCounter& Counter);
    /** The Belmonte region's origin; false when the region is not in this world. */
    YORIMICHI_API bool RegionOrigin(const UObject* WorldContext, FVector& OutCm);
    /** The local player may open the betting window here (on foot, free, at the counter). */
    YORIMICHI_API bool CanUse(const AWandererCharacter* Pawn);
    /** Interact at the counter: opens the betting window; false when the player is not there. */
    YORIMICHI_API bool TryOpen(AWandererCharacter* Pawn);
    YORIMICHI_API bool IsOpen();
    YORIMICHI_API void Close();
    /** Live and QA: the window's selection, step and message, as JSON ("{}" when closed). */
    YORIMICHI_API FString WindowJson();
    /** Travels the local player to the counter. */
    YORIMICHI_API bool GoTo(AWandererCharacter* Pawn);
}

/**
 * A player's wallet and win bets (docs/RACING.md, "Betting"), on each player controller. The host (ARacingService) fills
 * its view, replicated to the owner only, and the race card while the owner's betting window is open. A client asks the
 * host for a bet (ServerPlaceBet); the host validates it against the rules and answers (ClientBetReply). Offline and on
 * the host the same calls run directly.
 */
UCLASS(ClassGroup = Racing)
class YORIMICHI_API URacingWallet : public UActorComponent
{
    GENERATED_BODY()
public:
    URacingWallet();
    virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

    /** The local player's wallet (its first player controller's), or nullptr. */
    static URacingWallet* Local(const UObject* WorldContext);
    static URacingWallet* Of(const AController* Controller);

    const FRacingWalletView& GetView() const { return View; }
    const FRacingCard& GetCard() const { return Card; }
    /** Bumped whenever the view or the card changes on this machine (the window redraws then, never per frame). */
    uint32 GetRevision() const { return Revision; }

    // ------------------------------------------------------------------ owner
    /** The betting window opens or closes: the host sends the race card only while it is open. */
    void SetCounterOpen(bool bOpen);
    /** Asks the host for a win bet. Returns the request's serial, 0 when one is still waiting for its answer. */
    uint32 RequestBet(const FString& RaceKey, const FString& HorseId, int32 Stake);
    bool IsPending() const { return PendingSeq != 0; }
    /** The last answer: its serial and the refusal (empty: the bet was taken). */
    uint32 GetReplySeq() const { return ReplySeq; }
    const FString& GetReplyError() const { return ReplyError; }
    /** The last settled ticket's line for the HUD ("Pari gagnant · …"), with its opacity; empty when none is showing. */
    FString GetToast(float& Alpha) const;

    // ------------------------------------------------------------------ host
    /** The rules' player id this wallet belongs to (set by the service). */
    FString HostPlayerId;
    bool WantsCard() const { return bCounterOpen; }
    void HostSetView(const FRacingWalletView& Next);
    void HostSetCard(const FRacingCard& Next);
    /** The host's handling of a request from this wallet's owner (ServerPlaceBet, or a local request): the request is
     *  checked, then the service places it with the rules (ARacingService::PlaceBet). Empty when taken. */
    FString HostHandle(const FRacingBetRequest& Request, ARacingService* Service);
    /** What replication does on the owner (OnRep_View): tests feed the view a client would receive. */
    void ApplyReplicatedView(const FRacingWalletView& Next) { const FRacingWalletView Before = View; View = Next; OnRep_View(Before); }
    /** The owner's handling of an answer (ClientBetReply, or a local request's). */
    void ApplyReply(uint32 Seq, const FString& Error);

    UFUNCTION(Server, Reliable) void ServerSetCounter(bool bOpen);
    UFUNCTION(Server, Reliable) void ServerPlaceBet(const FRacingBetRequest& Request);
    UFUNCTION(Client, Reliable) void ClientBetReply(uint32 Seq, const FString& Error);

private:
    UPROPERTY(ReplicatedUsing = OnRep_View) FRacingWalletView View;
    UPROPERTY(ReplicatedUsing = OnRep_Card) FRacingCard Card;
    UFUNCTION() void OnRep_View(const FRacingWalletView& Before);
    UFUNCTION() void OnRep_Card();
    /** A ticket that was open and is now settled: the HUD's result line. */
    void Announce(const FRacingWalletView& Before, const FRacingWalletView& After);

    bool bCounterOpen = false;
    uint32 Revision = 0, NextSeq = 1, PendingSeq = 0, ReplySeq = 0;
    double PendingSince = 0., LastRequest = -1.;
    FString ReplyError, Toast;
    double ToastAt = -100.;
};
