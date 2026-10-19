#pragma once
#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "GameFramework/Actor.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "RacingStables.generated.h"

class FJsonObject;

class AController;
class ARacingService;
class AWandererCharacter;
class UMaterialInterface;
class UStaticMeshComponent;
class UTextRenderComponent;
struct FHRWorldState;

/** One of the player's horses, as its stall plate and the stable window show it (docs/RACING.md, "Stables"). */
USTRUCT()
struct FRacingStableHorse
{
    GENERATED_BODY()
    UPROPERTY() FString Id;
    UPROPERTY() FString Name;
    UPROPERTY() bool bMare = false;
    /** "4 ans 2 mois" (horse years). */
    UPROPERTY() FString Age;
    /** The rules' four abilities in whole points: start, speed, stamina, composure. */
    UPROPERTY() TArray<uint8> Abilities;
    /** The rules' public card score (HRRules::CardScore). */
    UPROPERTY() int32 Score = 0;
    /** 0 exhausted .. 3 fresh. */
    UPROPERTY() uint8 Condition = 3;
    UPROPERTY() int32 Starts = 0;
    UPROPERTY() int32 Wins = 0;
    UPROPERTY() int32 Podiums = 0;
    UPROPERTY() int32 Earnings = 0;
    /** One French line: entered, resting, injured, too young, at grass, retired. */
    UPROPERTY() FString Status;
    /** Entered for the next race days (not resting), and fit to race now. */
    UPROPERTY() bool bEntered = false;
    UPROPERTY() bool bCanRace = false;
    /** On the sale list (Price is then its asking price, else its value, HRRules::SaleValue). */
    UPROPERTY() bool bListed = false;
    UPROPERTY() int32 Price = 0;
    /** Today's race it runs in ("Lantern Sprint · course 2") and its start (world second), empty when none. */
    UPROPERTY() FString Today;
    UPROPERTY() double TodayStart = 0.;
    /** It may be bred now; else Breeding says why (in foal, too young...). */
    UPROPERTY() bool bCanBreed = false;
    UPROPERTY() FString Breeding;
};

/** A jockey: one of the stable's three, or one on the transfer board. */
USTRUCT()
struct FRacingStableRider
{
    GENERATED_BODY()
    UPROPERTY() FString Id;
    UPROPERTY() FString Name;
    /** Two-letter country. */
    UPROPERTY() FString Country;
    /** The stable it rides for ("" a free agent) and a legend's title. */
    UPROPERTY() FString Stable;
    UPROPERTY() FString Legend;
    /** The rules' four displayed stats 1..10 (start, tactics, composure, finish) and their sum, the overall (4..40). */
    UPROPERTY() TArray<uint8> Stats;
    UPROPERTY() int32 Overall = 0;
    /** Years. */
    UPROPERTY() int32 Age = 0;
    /** Fixed salary per race day; for a rider on the board, what it would earn with this stable. */
    UPROPERTY() int32 Wage = 0;
    /** Transfer price (listed), 0 for a free agent or a rider not on the list. */
    UPROPERTY() int32 Price = 0;
    UPROPERTY() int32 Rides = 0;
    UPROPERTY() int32 Wins = 0;
    UPROPERTY() bool bListed = false;
};

/** A horse on offer: a market recruit ("market:prospect", "market:adult"), another stable's listing, or a partner for a
 *  covering (Price is then the covering's whole cost). */
USTRUCT()
struct FRacingStableOffer
{
    GENERATED_BODY()
    UPROPERTY() FString Key;
    UPROPERTY() FString Name;
    UPROPERTY() FString Seller;
    UPROPERTY() FString Age;
    UPROPERTY() bool bMare = false;
    UPROPERTY() TArray<uint8> Abilities;
    UPROPERTY() int32 Score = 0;
    UPROPERTY() int32 Price = 0;
    UPROPERTY() int32 Wins = 0;
};

/** The player's stable, replicated to its owner only (URacingStableDesk). */
USTRUCT()
struct FRacingStableView
{
    GENERATED_BODY()
    /** The player owns a stable. */
    UPROPERTY() bool bActive = false;
    /** A guest's stable: theirs for this session only. */
    UPROPERTY() bool bSession = false;
    /** RacingStables::Sites() id ("belmonte", "hidamari"). */
    UPROPERTY() FString Site;
    UPROPERTY() FString StableId;
    UPROPERTY() FString Name;
    UPROPERTY() FColor Color = FColor::White;
    UPROPERTY() int32 Day = 0;
    UPROPERTY() int32 Coins = 0;
    /** What each race day's close takes from the wallet: the horses' upkeep and the jockeys' salaries (HRRules::DailyUpkeep),
     *  and of it the salaries alone. */
    UPROPERTY() int32 DailyCosts = 0;
    UPROPERTY() int32 Wages = 0;
    /** Horses in stall order (stall i shows horse i). */
    UPROPERTY() TArray<FRacingStableHorse> Horses;
    UPROPERTY() TArray<FRacingStableRider> Jockeys;
};

/** The transfer board and the market, sent only while the owner is at their stable. */
USTRUCT()
struct FRacingStableMarket
{
    GENERATED_BODY()
    UPROPERTY() int32 Day = 0;
    /** Listed riders of other stables and free agents, best first. */
    UPROPERTY() TArray<FRacingStableRider> Riders;
    /** Today's two market recruits, then other stables' listed horses. */
    UPROPERTY() TArray<FRacingStableOffer> Horses;
    /** Other stables' horses open to a covering now (the price: the service and the fee). */
    UPROPERTY() TArray<FRacingStableOffer> Studs;
};

/** What a stable request asks (docs/RACING.md, "Stables"). */
enum class ERacingStableAction : uint8
{
    Enter,          // Target: a horse of the stable: entered for the race days to come
    Rest,           // Target: kept out of the race days to come
    BuyHorse,       // Target: "market:prospect", "market:adult" or a listed horse
    SellHorse,      // Target: put on the sale list at its value
    Withdraw,       // Target: taken off the sale list
    Breed,          // Target: the stable's horse, Other: its partner (the stable's or another's)
    HireRider,      // Target: a listed rider (its price) or a free agent
    ListRider,      // Target: one of the stable's jockeys, on the transfer list at its value
    UnlistRider,
    ReleaseRider,
    Count
};

USTRUCT()
struct FRacingStableRequest
{
    GENERATED_BODY()
    UPROPERTY() uint32 Seq = 0;
    UPROPERTY() uint8 Action = 0;
    UPROPERTY() FString Target;
    UPROPERTY() FString Other;
};

/**
 * The player stables of racing V1 (docs/RACING.md, "Stables"): which places are player stables, who gets which, and the
 * stable requests, as glue between the game and the HorseRacing rules (HRRules: the rules decide, these only ask them
 * and say it in French). Pure functions over a world, so tests and every host reach the same state.
 */
namespace RacingStables
{
    /** Who may get a site: the host's own (persistent) player only, or any player, a guest included. */
    enum class EClaim : uint8 { HostPlayer, AnyPlayer };
    struct FSiteDef
    {
        /** The site's id ("belmonte", "hidamari") and the rules' stable it is. */
        const TCHAR* Id;
        const TCHAR* StableId;
        /** The stable's name and colour once a player has it (nullptr: the rules' own). */
        const TCHAR* Name;
        const TCHAR* Color;
        EClaim Claim;
        /** Where it is, for the window's header. */
        const TCHAR* Place;
    };
    /** The player stables in the order they are given: Belmonte's "Votre écurie" estate (the rules' stable for sale) to
     *  the host's player, then the Hidamari stable to the next player. */
    YORIMICHI_API const TArray<FSiteDef>& Sites();
    YORIMICHI_API int32 SiteIndexOfStable(const FString& StableId);

    /**
     * Gives a player their stable, free, at once (no quest): the first site in Sites() order whose stable no player owns
     * and that the player may claim. The rules' stable for sale is bought for them (with its riders), an unowned one is
     * taken over, a missing one founded (HRRules::FoundStable) under the site's id; its jockeys ride. Empty when the player
     * has their stable, else why not (no site left).
     */
    YORIMICHI_API FString Assign(FHRWorldState& S, const FString& PlayerId);
    /** The player's stable goes back to the world: a computer stable that keeps its horses and jockeys and races on. */
    YORIMICHI_API void Release(FHRWorldState& S, const FString& PlayerId);
    /** Every stable a guest's session player owns is released (what a save keeps of them: guests have no identity yet). */
    YORIMICHI_API void ReleaseSessionStables(FHRWorldState& S);
    /** Renames a stable everywhere the world refers to it. False when From is missing or To taken. */
    YORIMICHI_API bool RenameStable(FHRWorldState& S, const FString& From, const FString& To);

    /** Runs one request for a player with the rules; empty when done, else the refusal in French. */
    YORIMICHI_API FString Apply(FHRWorldState& S, const FString& PlayerId, const FRacingStableRequest& Request);
    /** The rules' refusals (English) in the game's French; an unknown one is passed on as it is. */
    YORIMICHI_API FString French(const FString& Refusal);

    YORIMICHI_API void BuildView(const FHRWorldState& S, const FString& PlayerId, FRacingStableView& Out);
    YORIMICHI_API void BuildMarket(const FHRWorldState& S, const FString& PlayerId, FRacingStableMarket& Out);

    // ------------------------------------------------------------------ the stable in the world
    enum class EAnchor : uint8 { Plate, Jockeys, Transfers };
    /** A place on the stable where its information hangs: a stall's name plate or a board. X of At faces out. */
    struct FAnchor
    {
        EAnchor Kind = EAnchor::Plate;
        int32 Stall = 0;
        FTransform At;
        /** Width and height, cm. */
        FVector2D Size = FVector2D::ZeroVector;
    };
    /** Belmonte's Val d'Oro stables ("Votre écurie"): the stall doors' plates and the two boards beside the main door,
     *  from runtime.json's racing_places.belmonte_stable (derived from the estate's committed placement by
     *  world/regions/belmonte/build.py), round the Belmonte region's origin. False (none) when absent or invalid. */
    YORIMICHI_API bool BelmonteAnchors(const TSharedPtr<FJsonObject>& Places, const FVector& OriginCm, TArray<FAnchor>& Out);
    /** The Hidamari stable's plates and its office's cork board (halved: jockeys, transfers), from its stable.json
     *  (world/regions/hidamari_stable). False when the text is not such a file. */
    YORIMICHI_API bool HidamariAnchors(const FString& Json, TArray<FAnchor>& Out);
    /** A site's anchors in this world; false when its place is not in the world. */
    YORIMICHI_API bool SiteAnchors(const UObject* WorldContext, const FString& Site, TArray<FAnchor>& Out);

    /** What a stall plate, the jockeys' board and the transfer board say (Latin-1 only: world text). */
    YORIMICHI_API FString PlateText(const FRacingStableView& View, int32 Stall);
    YORIMICHI_API FString JockeysText(const FRacingStableView& View);
    YORIMICHI_API FString TransfersText(const FRacingStableMarket& Market);

    /** The anchor the local player stands at (within reach, facing it), INDEX_NONE when none. */
    YORIMICHI_API int32 AnchorInReach(const TArray<FAnchor>& Anchors, const FVector& Location);
    /** The HUD's prompt at the local player's stable ("Lire : Bella"), empty when none. */
    YORIMICHI_API FString Prompt(const AWandererCharacter* Pawn);
    /** Interact at a plate or a board of the player's stable: opens the stable window there. */
    YORIMICHI_API bool TryOpen(AWandererCharacter* Pawn);
    YORIMICHI_API bool IsOpen();
    YORIMICHI_API void Close();
    /** Live and QA: the window's page, selection and message, as JSON ("null" when closed). */
    YORIMICHI_API FString WindowJson();
    /** Travels the local player in front of an anchor of their stable: "plate <n>", "jockeys" or "transfers". */
    YORIMICHI_API bool GoTo(AWandererCharacter* Pawn, const FString& Spot);
}

/**
 * A player's stable desk (docs/RACING.md, "Stables"), on each player controller: the host fills the stable's view,
 * replicated to its owner only, and the market while the owner is at their stable. A client asks the host
 * (ServerRequest); the host checks the request and the rules decide (ARacingService::ApplyStableRequest), then it answers
 * (ClientReply). Offline and on the host the same calls run directly.
 */
UCLASS(ClassGroup = Racing)
class YORIMICHI_API URacingStableDesk : public UActorComponent
{
    GENERATED_BODY()
public:
    URacingStableDesk();
    virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
    virtual void BeginPlay() override;

    static URacingStableDesk* Local(const UObject* WorldContext);
    static URacingStableDesk* Of(const AController* Controller);

    const FRacingStableView& GetView() const { return View; }
    const FRacingStableMarket& GetMarket() const { return Market; }
    uint32 GetRevision() const { return Revision; }

    // ------------------------------------------------------------------ owner
    /** The owner is at their stable (its boards are drawn) or has its window open: the host sends the market then. */
    void SetBrowsing(bool bOn);
    /** Asks the host. Returns the request's serial, 0 when one is still waiting for its answer. */
    uint32 Request(ERacingStableAction Action, const FString& Target, const FString& Other = FString());
    bool IsPending() const { return PendingSeq != 0; }
    uint32 GetReplySeq() const { return ReplySeq; }
    const FString& GetReplyError() const { return ReplyError; }

    // ------------------------------------------------------------------ host
    FString HostPlayerId;
    bool WantsMarket() const { return bBrowsing; }
    void HostSetView(const FRacingStableView& Next);
    void HostSetMarket(const FRacingStableMarket& Next);
    /** The host's handling of a request from this desk's owner: sizes and the action checked, then the rules. */
    FString HostHandle(const FRacingStableRequest& Request, ARacingService* Service);
    /** What replication does on the owner (tests feed it what a client would receive). */
    void ApplyReplicatedView(const FRacingStableView& Next) { View = Next; OnRep_View(); }
    void ApplyReply(uint32 Seq, const FString& Error);

    UFUNCTION(Server, Reliable) void ServerSetBrowsing(bool bOn);
    UFUNCTION(Server, Reliable) void ServerRequest(const FRacingStableRequest& Request);
    UFUNCTION(Client, Reliable) void ClientReply(uint32 Seq, const FString& Error);

    /** At most five requests a second are looked at. */
    static constexpr double MinRequestGap = .2;

private:
    UPROPERTY(ReplicatedUsing = OnRep_View) FRacingStableView View;
    UPROPERTY(ReplicatedUsing = OnRep_Market) FRacingStableMarket Market;
    UFUNCTION() void OnRep_View();
    UFUNCTION() void OnRep_Market();

    bool bBrowsing = false, bBrowsingAsked = false;
    uint32 Revision = 0, NextSeq = 1, PendingSeq = 0, ReplySeq = 0;
    double PendingSince = 0., LastRequest = -1.;
    FString ReplyError;
};

/**
 * The player's stable in the world, drawn on this machine only (never a dedicated server): a name plate on every stall
 * door with its horse's name and stats, the jockeys' board and the transfer board, from the owner's desk view. They
 * exist only while the local player is within reach of their own stable, and are rewritten when the view changes.
 */
UCLASS(NotPlaceable)
class YORIMICHI_API ARacingStableBoards : public AActor
{
    GENERATED_BODY()
public:
    ARacingStableBoards();
    static ARacingStableBoards* Find(const UObject* WorldContext);
    static ARacingStableBoards* Ensure(UWorld* World);
    virtual void Tick(float DeltaSeconds) override;
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;

    /** The local player's stable's anchors (empty away from it). */
    const TArray<RacingStables::FAnchor>& GetAnchors() const { return Anchors; }
    FString GetSite() const { return Site; }
    int32 NumShown() const { return Texts.Num(); }
    /** The local player is within this distance (cm) of their stable: its boards are built. */
    static constexpr double ShowRadius = 4500.;

private:
    void Clear();
    void Build();
    void Write();
    TArray<RacingStables::FAnchor> Anchors;
    FString Site;
    UPROPERTY() TArray<TObjectPtr<UStaticMeshComponent>> Backs;
    UPROPERTY() TArray<TObjectPtr<UTextRenderComponent>> Texts;
    UPROPERTY() TObjectPtr<UMaterialInterface> BackMaterial;
    uint32 Written = MAX_uint32;
    float NextCheck = 0.f;
};

/** Live-bridge helpers (atelier live py) for the stables. */
UCLASS()
class YORIMICHI_API URacingStableLive : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()
public:
    /** The local player's stable view, the market, the anchor in reach, the boards shown and the window, as JSON. */
    UFUNCTION(BlueprintCallable, Category = "Live") static FString RacingStable();
    /** Travels before "plate <n>", "jockeys" or "transfers" of the local player's stable. */
    UFUNCTION(BlueprintCallable, Category = "Live") static bool RacingStableGo(const FString& Spot);
    /** Interact as the player does at the anchor in reach: opens the stable window. */
    UFUNCTION(BlueprintCallable, Category = "Live") static bool RacingStableOpen();
    /** A request as the window sends it: action "enter", "rest", "buy", "sell", "withdraw", "breed", "hire", "list",
     *  "unlist" or "release". Returns its serial (0: refused before sending). */
    UFUNCTION(BlueprintCallable, Category = "Live") static int32 RacingStableAct(const FString& Action, const FString& Target, const FString& Other);
};
