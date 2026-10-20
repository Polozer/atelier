#pragma once
#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "GameFramework/Actor.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "RacingRecords.generated.h"

class FJsonObject;

class ARacingService;
class AWandererCharacter;
class UMaterialInterface;
class UStaticMeshComponent;
class UTextRenderComponent;
struct FHRCareerLine;
struct FHRRider;
struct FHRWorldState;

/**
 * The records hall of Belmonte's town hall, the "salle des courses" (docs/RACING.md, "Records hall"): every statistic of
 * the racing world, hung on objects in the Palazzo Comunale's loggia and read close up one page at a time. The rules'
 * world (HRRules) keeps careers and totals; what it does not keep (the best times, who rode them, a jockey's Grand Prix,
 * earnings and streaks) the host notes in a small ledger as races are seen run, saved beside the world.
 */

/** Best time on one circuit at one distance, or in one Grand Prix's final or heats. */
struct FRacingRecordTime
{
    /** "c:<circuit>:<distance>" or "gp:<event id>:final|heats". */
    FString Key;
    int32 Distance = 0;
    int64 TimeUs = 0;
    FString HorseId, Horse, RiderId, Jockey, StableId, Stable;
    /** The race day it was set, and the race ("Lantern Sprint · course 2"). */
    int32 T = 0;
    FString Race;
};

/** What the rules do not count for a rider (a stable's jockey or a player riding): kept by the ledger. */
struct FRacingRiderTally
{
    FString Name;
    int32 Rides = 0, Wins = 0, GpWins = 0, Earnings = 0, Streak = 0, BestStreak = 0;
};

/** The host's ledger (Saved/racing/records.json): the record times and the riders' tallies since the hall opened. */
struct YORIMICHI_API FRacingLedger
{
    static constexpr int32 Version = 1;
    /** Admission bounds of a saved ledger (FromJson): record keys (circuits x distances, Grands Prix) and noted races. */
    static constexpr int32 MaxRecords = 4096, MaxSeen = 4096;
    /** The world it belongs to (its seed): another world starts a new ledger. */
    FString Seed;
    /** The first race day it saw. */
    int32 SinceT = -1;
    TArray<FRacingRecordTime> Records;
    TMap<FString, FRacingRiderTally> Riders;
    /** Races already noted ("<day>:<race key>"), today's and yesterday's only. */
    TSet<FString> Seen;
    /** Bumped at every change. */
    uint32 Revision = 0;

    const FRacingRecordTime* Find(const FString& Key) const { return Records.FindByPredicate([&Key](const FRacingRecordTime& R) { return R.Key == Key; }); }
    FString ToJson() const;
    /** False (Out untouched) when the text is not an admissible ledger of this version: bounded collections and strings,
     *  unique record keys, finite non-negative counts, wins <= rides, streak <= wins and best streak >= streak. */
    static bool FromJson(const FString& Json, FRacingLedger& Out);
};

/** The hall's objects. */
enum class ERacingHallObject : uint8 { Board, Record, Honour, Cabinet, Archive, Plaque, Count };
/** Who a list, an honour board or a card is about. */
enum class ERacingHallKind : uint8 { Horse, Jockey, Stable, Count };
/** The honour boards. */
enum class ERacingHonour : uint8 { Wins, Defeats, GrandPrix, Earnings, Streak, Count };

/** What the reader asks the host for: one page of one object (docs/RACING.md, "Records hall"). */
USTRUCT()
struct FRacingRecordsQuery
{
    GENERATED_BODY()
    UPROPERTY() uint32 Seq = 0;
    /** ERacingHallObject. */
    UPROPERTY() uint8 Object = 0;
    /** The record panel (RacingRecords::Panels()) or the honour board (ERacingHonour). */
    UPROPERTY() uint8 Index = 0;
    /** ERacingHallKind: the cabinet's drawer, the honour board's column, the archive's register. */
    UPROPERTY() uint8 Kind = 0;
    /** The cabinet: 0 by name, 1 by wins, 2 by earnings. The archive: 0 newest first, 1 by name. */
    UPROPERTY() uint8 Sort = 0;
    /** Part of a name (accents and case ignored). */
    UPROPERTY() FString Search;
    UPROPERTY() int32 Page = 0;
    /** A card: "horse:<id>", "jockey:<id>" or "stable:<id>"; empty for the object's list. */
    UPROPERTY() FString Subject;
};

USTRUCT()
struct FRacingRecordsLine
{
    GENERATED_BODY()
    UPROPERTY() FString Left;
    UPROPERTY() FString Right;
    UPROPERTY() FString Sub;
    /** The card this line opens ("horse:<id>"...), empty when none. */
    UPROPERTY() FString Subject;
    /** A heading line (no selection). */
    UPROPERTY() bool bHeading = false;
};

/** One page as the reader sees it, built by the host for the query of the same Seq. */
USTRUCT()
struct FRacingRecordsPage
{
    GENERATED_BODY()
    UPROPERTY() uint32 Seq = 0;
    UPROPERTY() FRacingRecordsQuery Query;
    /** Small capitals over the title ("SALLE DES COURSES · FICHIER") and the title. */
    UPROPERTY() FString Kicker;
    UPROPERTY() FString Title;
    UPROPERTY() FString Intro;
    UPROPERTY() TArray<FRacingRecordsLine> Lines;
    UPROPERTY() int32 Page = 0;
    UPROPERTY() int32 Pages = 1;
    UPROPERTY() int32 Total = 0;
    /** The refusal (French), empty when the page was built. */
    UPROPERTY() FString Error;
};

/** What the hall's objects show from afar, sent while the reader is in the hall (each text Latin-1). */
USTRUCT()
struct FRacingHallBoards
{
    GENERATED_BODY()
    UPROPERTY() int32 Day = 0;
    /** The split-flap board's two halves: the standings and the next races. */
    UPROPERTY() FString Standings;
    UPROPERTY() FString Upcoming;
    /** One text per record panel (RacingRecords::Panels()) and per honour board (ERacingHonour). */
    UPROPERTY() TArray<FString> Records;
    UPROPERTY() TArray<FString> Honours;
    UPROPERTY() FString Cabinet;
    UPROPERTY() FString Archive;
};

namespace RacingRecords
{
    // ------------------------------------------------------------------ the ledger (host)
    /** The circuits: Hidamari's oval, Belmonte's turf and its sand. */
    YORIMICHI_API int32 CircuitOf(int32 T);
    YORIMICHI_API const TCHAR* CircuitName(int32 Circuit);
    /**
     * Notes the races of the world's meeting into the ledger: each run race once, when its winner is home at world second
     * Now (as the race is seen), or every run race when bAll (the day is about to close). Record times, then each rider's
     * rides, wins, Grand Prix, earnings and streaks. True when the ledger changed.
     */
    YORIMICHI_API bool Note(FRacingLedger& L, const FHRWorldState& S, double Now, bool bAll);

    // ------------------------------------------------------------------ what the hall shows (pure)
    /** A rider is archived as a horse is (HRClock::ArchiveDays after retiring); a horse when the rules archive it. */
    YORIMICHI_API bool IsArchived(const FHRRider& R, int32 T);
    /** The longest run of consecutive wins in a career (in its order). */
    YORIMICHI_API int32 LongestStreak(const TArray<FHRCareerLine>& Career);

    /** One horse, jockey or stable's numbers for the honour boards and the cards. */
    struct FTally
    {
        FString Subject, Name, Detail;
        int32 Starts = 0, Wins = 0, Defeats = 0, GrandPrix = 0, Earnings = 0, Streak = 0;
        bool bArchived = false;
        /** Archived on this day (-1 when not). */
        int32 ArchivedT = -1;
        int32 Value(ERacingHonour H) const;
    };
    /** Every horse, jockey or stable the world knows, archived ones included. */
    YORIMICHI_API TArray<FTally> Tallies(const FHRWorldState& S, const FRacingLedger& L, ERacingHallKind Kind);
    /** The best of one honour, best first (ties by name), those with nothing left out. */
    YORIMICHI_API TArray<FTally> Ranking(const FHRWorldState& S, const FRacingLedger& L, ERacingHallKind Kind, ERacingHonour Honour);

    /** The record panels: the three circuits, then the four Grands Prix in season order. */
    struct FPanel { int32 Circuit = -1; FString EventId; FString Name; };
    YORIMICHI_API const TArray<FPanel>& Panels();

    /** "1:12.34" or "52.31 s". */
    YORIMICHI_API FString Time(int64 TimeUs);
    /** "saison 2, jour 5". */
    YORIMICHI_API FString Date(int32 T);
    YORIMICHI_API const TCHAR* HonourName(ERacingHonour H);

    /** Lines per page of a list. */
    inline constexpr int32 PageLines = 8;
    /** The page a query asks for, from the world and the ledger at world second Now. */
    YORIMICHI_API void BuildPage(const FHRWorldState& S, const FRacingLedger& L, double Now, const FRacingRecordsQuery& Q, FRacingRecordsPage& Out);
    /** The hall's objects' texts. */
    YORIMICHI_API void BuildBoards(const FHRWorldState& S, const FRacingLedger& L, double Now, FRacingHallBoards& Out);
    /** Why a query is not valid ("" when it is): sizes and enums, before any work. */
    YORIMICHI_API FString Refusal(const FRacingRecordsQuery& Q);

    // ------------------------------------------------------------------ the hall in the world
    /** A place in the hall: a board on a wall or a piece of furniture. X of At faces the reader; Floor is the loggia's. */
    struct FAnchor
    {
        ERacingHallObject Object = ERacingHallObject::Board;
        uint8 Index = 0;
        FTransform At;
        /** Width and height, cm. */
        FVector2D Size = FVector2D::ZeroVector;
        double Floor = 0.;
    };
    /** The Palazzo Comunale's loggia: its objects and its centre (the loggia's middle, on its floor) from runtime.json's
     *  racing_places.records_hall (derived from the palazzo's committed placement by world/regions/belmonte/build.py),
     *  round the Belmonte region's origin. False (none) when absent, invalid or incomplete. */
    YORIMICHI_API bool HallAnchors(const TSharedPtr<FJsonObject>& Places, const FVector& OriginCm, TArray<FAnchor>& Out, FVector& OutCentre);
    /** The anchor a reader at Location stands at (in front of it, within reach, and, given the way they face, the one they
     *  look at), INDEX_NONE when none. */
    YORIMICHI_API int32 AnchorInReach(const TArray<FAnchor>& Anchors, const FVector& Location, const FVector& Facing = FVector::ZeroVector);
    /** The first query of an object. */
    YORIMICHI_API FRacingRecordsQuery FirstQuery(const FAnchor& A);

    /** The HUD's prompt in the hall ("Lire : Records de Belmonte"), empty when none. */
    YORIMICHI_API FString Prompt(const AWandererCharacter* Pawn);
    YORIMICHI_API bool TryOpen(AWandererCharacter* Pawn);
    YORIMICHI_API bool IsOpen();
    YORIMICHI_API void Close();
    /** Live and QA: the reader's query, page and selection, as JSON ("null" when closed). */
    YORIMICHI_API FString WindowJson();
    /** Travels the local player before an object: "board", "record <n>", "honour <n>", "cabinet", "archive". */
    YORIMICHI_API bool GoTo(AWandererCharacter* Pawn, const FString& Spot);
    /** Live: what the open reader does on a key ("up", "down", "accept", "back", "next", "prev", "kind", "sort",
     *  "letter", or "type:<text>"). False when it is closed. */
    YORIMICHI_API bool Press(const FString& Key);
}

/**
 * A player's reading desk in the records hall, on each player controller: the page they read and, while they are in the
 * hall, its objects' texts, both replicated to the owner only and only on demand. A client asks the host for a page
 * (ServerAsk); the host checks the query and builds it from the world and the ledger (ARacingService). Offline and on the
 * host the same calls run directly.
 */
UCLASS(ClassGroup = Racing)
class YORIMICHI_API URacingRecordsDesk : public UActorComponent
{
    GENERATED_BODY()
public:
    URacingRecordsDesk();
    virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
    virtual void BeginPlay() override;

    static URacingRecordsDesk* Local(const UObject* WorldContext);
    static URacingRecordsDesk* Of(const AController* Controller);

    const FRacingRecordsPage& GetPage() const { return Page; }
    const FRacingHallBoards& GetBoards() const { return Boards; }
    uint32 GetRevision() const { return Revision; }

    // ------------------------------------------------------------------ owner
    /** The owner is in the hall: the host sends its objects' texts then. */
    void SetInHall(bool bOn);
    /** Asks the host for a page. Returns the query's serial, 0 when it was not sent (too soon after the last one). */
    uint32 Ask(FRacingRecordsQuery Query);
    bool IsPending() const { return PendingSeq != 0; }

    // ------------------------------------------------------------------ host
    bool WantsBoards() const { return bInHall; }
    void HostSetBoards(const FRacingHallBoards& Next);
    /** The host's handling of a query: checked, then built (ARacingService::BuildRecordsPage). */
    void HostHandle(const FRacingRecordsQuery& Query, ARacingService* Service);
    /** What replication does on the owner (tests feed it what a client would receive). */
    void ApplyReplicatedPage(const FRacingRecordsPage& Next) { Page = Next; OnRep_Page(); }

    UFUNCTION(Server, Reliable) void ServerSetInHall(bool bOn);
    UFUNCTION(Server, Reliable) void ServerAsk(const FRacingRecordsQuery& Query);

    /** At most ten pages a second are built. */
    static constexpr double MinAskGap = .1;

private:
    UPROPERTY(ReplicatedUsing = OnRep_Page) FRacingRecordsPage Page;
    UPROPERTY(ReplicatedUsing = OnRep_Boards) FRacingHallBoards Boards;
    UFUNCTION() void OnRep_Page();
    UFUNCTION() void OnRep_Boards();

    bool bInHall = false, bInHallAsked = false;
    uint32 Revision = 0, NextSeq = 1, PendingSeq = 0;
    double LastAsk = -1., LastServed = -1.;
};

/**
 * The records hall in the world, drawn on this machine only (never a dedicated server): the split-flap board over the
 * loggia's middle door, the record panels and the title plaque between its doors and windows, the honour boards on its
 * end walls, the card cabinet and the archive table. Built only while the local player is within ShowRadius of the hall,
 * rewritten when the desk's texts change (at most once a second), culled beyond ShowRadius.
 */
UCLASS(NotPlaceable)
class YORIMICHI_API ARacingRecordsHall : public AActor
{
    GENERATED_BODY()
public:
    ARacingRecordsHall();
    static ARacingRecordsHall* Find(const UObject* WorldContext);
    static ARacingRecordsHall* Ensure(UWorld* World);
    virtual void Tick(float DeltaSeconds) override;
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;

    const TArray<RacingRecords::FAnchor>& GetAnchors() const { return Anchors; }
    int32 NumShown() const { return Texts.Num(); }
    /** The objects are built within this distance (cm) of the hall's centre. */
    static constexpr double ShowRadius = 4000.;

private:
    void Clear();
    void Build();
    void Write();
    TArray<RacingRecords::FAnchor> Anchors;
    FVector Centre = FVector::ZeroVector;
    UPROPERTY() TArray<TObjectPtr<UStaticMeshComponent>> Meshes;
    UPROPERTY() TArray<TObjectPtr<UTextRenderComponent>> Texts;
    /** Which anchor each text writes (INDEX_NONE: a fixed label). */
    TArray<int32> TextAnchor;
    UPROPERTY() TObjectPtr<UMaterialInterface> BackMaterial;
    uint32 Written = MAX_uint32;
    double LastWrite = -10.;
};

/** Live-bridge helpers (atelier live py) for the records hall. */
UCLASS()
class YORIMICHI_API URacingRecordsLive : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()
public:
    /** The ledger's size, the objects shown, the anchor in reach, the boards' texts and the reader, as JSON. */
    UFUNCTION(BlueprintCallable, Category = "Live") static FString RacingRecords();
    /** Travels before "board", "record <n>", "honour <n>", "cabinet" or "archive". */
    UFUNCTION(BlueprintCallable, Category = "Live") static bool RacingRecordsGo(const FString& Spot);
    /** Interact as the player does at the object in reach: opens the reader. */
    UFUNCTION(BlueprintCallable, Category = "Live") static bool RacingRecordsOpen();
    /** A key in the open reader (RacingRecords::Press). */
    UFUNCTION(BlueprintCallable, Category = "Live") static bool RacingRecordsPress(const FString& Key);
};
