#pragma once

#include "CoreMinimal.h"
#include "HRTypes.generated.h"

/**
 * Saved state of a horse racing world. Everything is plain data (saved as JSON, HRSave.h) and every random outcome comes
 * from the seeded hash in HRRandom, so a reload, a listen server and its clients replay exactly the same world.
 *
 * Time: T counts race days since the world's day 0. A race day lasts two real hours and a season of twelve race days is
 * one in-game year (24 real hours). Horses and riders age on a slower clock: one horse year is 84 race days, one real
 * week (HRClock.h). Fields named ...T are race days.
 */

/** Ability order everywhere: 0 start (acceleration), 1 speed, 2 endurance, 3 composure. */
namespace HRAbility
{
	constexpr int32 Acceleration = 0;
	constexpr int32 Speed = 1;
	constexpr int32 Endurance = 2;
	constexpr int32 Composure = 3;
	constexpr int32 Count = 4;
}

/** One gene: the allele from the mother and the one from the father (each 0..4 unless stated). */
USTRUCT(BlueprintType)
struct FHRGenePair
{
	GENERATED_BODY()

	UPROPERTY() int32 A = 0;
	UPROPERTY() int32 B = 0;

	FHRGenePair() = default;
	FHRGenePair(int32 InA, int32 InB) : A(InA), B(InB) {}
	int32 Sum() const { return A + B; }
	int32 operator[](int32 I) const { return I == 0 ? A : B; }
};

/** Tissue zone: 0 front tendons, 1 stifles, 2 back, 3 hind tendons. Fixed point values (x10000). */
USTRUCT(BlueprintType)
struct FHRZone
{
	GENERATED_BODY()

	UPROPERTY() int32 Structure = 0;
	UPROPERTY() int32 Acute = 0;
	UPROPERTY() int32 Recovery = 0;
	UPROPERTY() int32 Adaptation = 0;
	UPROPERTY() int32 InflammationGene = 0;
	UPROPERTY() int32 Load = 0;
	UPROPERTY() int32 Tolerance = 0;
	UPROPERTY() int32 Inflammation = 0;
	UPROPERTY() int32 Scars = 0;
};

USTRUCT(BlueprintType)
struct FHRInjury
{
	GENERATED_BODY()

	UPROPERTY() bool bActive = false;
	/** "soreness", "light", "moderate", "serious" or "career-ending". */
	UPROPERTY() FString Severity;
	/** "progressive", "extended" or empty (no plan yet). */
	UPROPERTY() FString Plan;
	/** Race days rested since the injury. */
	UPROPERTY() int32 Benches = 0;
	UPROPERTY() int32 Minimum = 0;
	UPROPERTY() int32 SinceT = 0;
};

/** Visible features decoded from the eight simple visual genes (a card silhouette); the 3D look is HRVisualGenome.h. */
USTRUCT(BlueprintType)
struct FHRAppearance
{
	GENERATED_BODY()

	UPROPERTY() int32 Family = 0;
	UPROPERTY() FString Coat;
	UPROPERTY() FString Mane;
	UPROPERTY() int32 Marking = 0;
	UPROPERTY() float Height = 0.5f;
	UPROPERTY() float Bulk = 0.5f;
	UPROPERTY() float LegLength = 0.5f;
	UPROPERTY() float Head = 0.5f;
	UPROPERTY() float Hair = 0.5f;
};

/** One line of a horse's record. */
USTRUCT(BlueprintType)
struct FHRCareerLine
{
	GENERATED_BODY()

	UPROPERTY() int32 T = 0;
	UPROPERTY() FString EventName;
	/** "village", "semi", "qualif", "barrage" or "final". */
	UPROPERTY() FString Round;
	UPROPERTY() int32 Place = 0;
	UPROPERTY() int32 Runners = 0;
	UPROPERTY() int32 Gross = 0;
	UPROPERTY() FString StableId;
	/** The race of that day ("village:1"): identifies head-to-heads. */
	UPROPERTY() FString RaceKey;
};

USTRUCT(BlueprintType)
struct FHRHorse
{
	GENERATED_BODY()

	UPROPERTY() FString Id;
	UPROPERTY() FString Name;
	UPROPERTY() FString Seed;
	/** Stable id, or "market" for a horse on offer. */
	UPROPERTY() FString OwnerId;
	UPROPERTY() bool bMare = false;
	UPROPERTY() int32 BirthT = 0;
	/** First race day it may race: one horse year after its birth. */
	UPROPERTY() int32 ReadyT = 0;
	UPROPERTY() int32 ScheduledRetirementT = 0;
	/** -1 while racing. */
	UPROPERTY() int32 RetiredT = -1;
	/** -1 until retirement; the day it goes to the archives (HRClock::ArchiveDays after retiring). */
	UPROPERTY() int32 BreedingUntilT = -1;
	UPROPERTY() int32 NextBreedingT = 0;
	/** "active", "pasture", "retired", "archive" or "offer" (market horse not yet bought). */
	UPROPERTY() FString Placement;
	/** "rival", "recruit", "starter", "foal" or "recovery". */
	UPROPERTY() FString Origin;
	UPROPERTY() TArray<FString> Parents;
	UPROPERTY() TMap<FString, FHRGenePair> Genome;
	UPROPERTY() TArray<int32> Abilities;
	UPROPERTY() TArray<int32> Ceilings;
	/** Learning response in percent: 70, 100 or 135. */
	UPROPERTY() TArray<int32> Response;
	UPROPERTY() TArray<int32> Progress;
	/** 0 exhausted .. 3 fresh. */
	UPROPERTY() int32 Condition = 3;
	UPROPERTY() TArray<FHRZone> Zones;
	UPROPERTY() int32 Stress = 0;
	UPROPERTY() FString Trait;
	/** 0 none, 1 or 2 chosen mastery. */
	UPROPERTY() int32 Mastery = 0;
	UPROPERTY() int32 Xp = 0;
	/** 0 firm, 1 soft, 2 sand. */
	UPROPERTY() int32 Favorite = 0;
	UPROPERTY() int32 Difficult = 0;
	UPROPERTY() FHRInjury Injury;
	UPROPERTY() int32 Starts = 0;
	UPROPERTY() int32 Wins = 0;
	UPROPERTY() int32 GpWins = 0;
	UPROPERTY() int32 Podiums = 0;
	UPROPERTY() int32 Earnings = 0;
	UPROPERTY() int32 Generation = 0;
	UPROPERTY() FHRAppearance Appearance;
	UPROPERTY() TArray<FHRCareerLine> Career;
	/** Stables that owned this horse, in order (first = breeder). */
	UPROPERTY() TArray<FString> Owners;

	bool IsRetired() const { return RetiredT >= 0; }
	int32 AbilitySum() const { int32 S = 0; for (int32 V : Abilities) S += V; return S; }
};

USTRUCT(BlueprintType)
struct FHRStable
{
	GENERATED_BODY()

	UPROPERTY() FString Id;
	UPROPERTY() FString Name;
	/** sRGB hex without '#'. */
	UPROPERTY() FString Color;
	/** Emblem index (the game decides what each one looks like). */
	UPROPERTY() int32 Emblem = 0;
	UPROPERTY() FString Motto;
	/** Initial situation only: "established", "rising", "rebuilding", "struggling", "forsale" or "player". */
	UPROPERTY() FString Profile;
	/** Listed for sale: runs no horse until a player buys it. */
	UPROPERTY() bool bForSale = false;
	/** The opaque id of the player who owns it; empty for a computer stable. Its money is that player's coins. */
	UPROPERTY() FString OwnerPlayerId;
	UPROPERTY() int32 Coins = 0;
	UPROPERTY() int32 Debt = 0;
	UPROPERTY() bool bRescueUsed = false;
	UPROPERTY() int32 Prestige = 0;
	UPROPERTY() int32 Renown = 0;
	UPROPERTY() int32 TotalEarnings = 0;
	UPROPERTY() int32 EventWins = 0;
	/** "<season>:<event id>" of every Grand Prix won. */
	UPROPERTY() TArray<FString> GpTitles;
	UPROPERTY() TArray<int32> GrandSlams;
	/** Day of the last acquisition or birth (one per day). */
	UPROPERTY() int32 AcquisitionT = -1;
	UPROPERTY() int32 TrainingT = -1;
	UPROPERTY() int32 TrainingUsed = 0;
	UPROPERTY() int32 Sales = 0;
	UPROPERTY() int32 Purchases = 0;
	UPROPERTY() int32 Births = 0;
	/** Running costs paid since the world began. */
	UPROPERTY() int32 UpkeepPaid = 0;

	bool IsPlayerOwned() const { return !OwnerPlayerId.IsEmpty(); }
	bool IsComputer() const { return !bForSale && OwnerPlayerId.IsEmpty(); }
};

/**
 * A human rider (jockey). Skills are in hundredths of the 1-10 scale (500 = 5.0); the curve fields are hidden from the
 * player, who only sees the rounded stats move. Ages are in rider months (HRClock::LifeMonth race days each).
 */
USTRUCT(BlueprintType)
struct FHRRider
{
	GENERATED_BODY()

	UPROPERTY() FString Id;
	UPROPERTY() FString Seed;
	UPROPERTY() FString FirstName;
	UPROPERTY() FString LastName;
	/** Name pool: "fr", "gb", "us", "la", "jp", "kr", "cn" or "vn". */
	UPROPERTY() FString Culture;
	/** Two-letter country shown next to the name. */
	UPROPERTY() FString Country;
	UPROPERTY() bool bFemale = false;
	UPROPERTY() int32 BirthT = 0;
	UPROPERTY() int32 DebutT = 0;
	/** Stable id, or empty for a free agent. */
	UPROPERTY() FString OwnerId;
	/** "", "sprinter", "flyer", "maestro" or "stayer". */
	UPROPERTY() FString Legend;
	/** -1 while riding. */
	UPROPERTY() int32 RetiredT = -1;
	/** 0 start, 1 tactics, 2 composure, 3 finish (hundredths). */
	UPROPERTY() TArray<int32> Skill;
	/** Skills at the start of the season: trend arrows compare against them. */
	UPROPERTY() TArray<int32> SeasonSkill;
	UPROPERTY() TArray<int32> Potential;
	/** Growth per rider month towards the potential, per mille. */
	UPROPERTY() int32 Growth = 25;
	/** Age in rider months when the peak starts, its length, the decline per month after it (hundredths). */
	UPROPERTY() int32 PeakAge = 336;
	UPROPERTY() int32 PeakMonths = 36;
	UPROPERTY() int32 Decline = 8;
	UPROPERTY() int32 RetireAge = 456;
	/** Rides counted when the career curve last stepped (the rides of the month since then add experience). */
	UPROPERTY() int32 CurveRides = 0;
	/** Look: height in cm, build 0 slim / 1 average / 2 heavy, head 0..3, hair 0..7, hair colour 0..5, skin 0..5, beard 0..4. */
	UPROPERTY() int32 Height = 165;
	UPROPERTY() int32 Build = 0;
	UPROPERTY() int32 Head = 0;
	UPROPERTY() int32 Hair = 0;
	UPROPERTY() int32 HairColor = 0;
	UPROPERTY() int32 Skin = 0;
	UPROPERTY() int32 Beard = 0;
	/** Fixed salary in coins per race day, set when the rider signs. */
	UPROPERTY() int32 Wage = 1;
	/** Transfer price when listed by its stable, 0 otherwise. */
	UPROPERTY() int32 ListedPrice = 0;
	/** Day the rider became a free agent (-1 under contract). */
	UPROPERTY() int32 FreeSinceT = -1;
	UPROPERTY() int32 Rides = 0;
	UPROPERTY() int32 Wins = 0;
	/** Stables the rider rode for, in order. */
	UPROPERTY() TArray<FString> Stables;

	bool IsRetired() const { return RetiredT >= 0; }
	FString FullName() const { return LastName.IsEmpty() ? FirstName : FirstName + TEXT(" ") + LastName; }
};

USTRUCT(BlueprintType)
struct FHRRunner
{
	GENERATED_BODY()

	UPROPERTY() FString HorseId;
	UPROPERTY() FString StableId;
	/** 0 safe, 1 patient, 2 fast start. */
	UPROPERTY() int32 Preparation = 0;
	/** The player riding this horse with their own rider skill (FHRPlayer::RiderSkill); empty: the stable's rider. */
	UPROPERTY() FString RiderPlayerId;
};

USTRUCT(BlueprintType)
struct FHRSegment
{
	GENERATED_BODY()

	UPROPERTY() double Distance = 0;
	UPROPERTY() int64 DurationUs = 0;
	UPROPERTY() int64 CumulativeUs = 0;
	UPROPERTY() int32 Rank = 0;
	UPROPERTY() int32 Form = 0;
};

USTRUCT(BlueprintType)
struct FHRIncident
{
	GENERATED_BODY()

	UPROPERTY() FString HorseId;
	UPROPERTY() int32 Beat = 0;
	/** "start", "bumped", "boxed" or "faded". */
	UPROPERTY() FString Kind;
	/** Two-run races: which run, 0 or 1. */
	UPROPERTY() int32 Run = 0;
};

USTRUCT(BlueprintType)
struct FHRFinish
{
	GENERATED_BODY()

	UPROPERTY() FString HorseId;
	UPROPERTY() FString StableId;
	UPROPERTY() FString HorseName;
	UPROPERTY() FString StableName;
	UPROPERTY() int32 Preparation = 0;
	UPROPERTY() int32 Place = 0;
	UPROPERTY() int64 TimeUs = 0;
	UPROPERTY() TArray<FHRSegment> Segments;
	UPROPERTY() int32 Gross = 0;
	UPROPERTY() int32 Points = 0;
	UPROPERTY() int32 Prestige = 0;
	UPROPERTY() int32 Xp = 0;
	/** Injury severity caused by this race, empty when none. */
	UPROPERTY() FString Injury;
	/** Two-run races: each run's time in microseconds; empty for a single run. */
	UPROPERTY() TArray<int64> RunTimesUs;
	/** Two-run races: the run whose time counts (TimeUs and Segments are that run's). */
	UPROPERTY() int32 BestRun = 0;
	/** The rider: a rider id, "player:<player id>" or empty (a hired jockey with no effect). */
	UPROPERTY() FString RiderId;
	UPROPERTY() FString RiderName;
};

/** One run of a two-run race: its own finishing order and times (the official result is the best time). */
USTRUCT(BlueprintType)
struct FHRRaceRun
{
	GENERATED_BODY()

	UPROPERTY() TArray<FHRFinish> Finishes;
};

/** How often one top-three order came up in the public replays ("2>0>4" by runner index). */
USTRUCT(BlueprintType)
struct FHROrderCount
{
	GENERATED_BODY()

	UPROPERTY() FString Key;
	UPROPERTY() int32 Count = 0;
};

USTRUCT(BlueprintType)
struct FHRRace
{
	GENERATED_BODY()

	/** "village:0", "semi:2", "qualif:1", "barrage:0", "final:0". */
	UPROPERTY() FString Key;
	UPROPERTY() FString Round;
	UPROPERTY() int32 Group = 0;
	UPROPERTY() FString EventId;
	UPROPERTY() int32 Distance = 0;
	/** "declared" (open to bets), "run", "uncontested" or "bye". */
	UPROPERTY() FString Status;
	UPROPERTY() TArray<FHRRunner> Entries;
	UPROPERTY() TArray<FHRFinish> Finishes;
	/** Two-run races: both runs in running order; empty for a single run. Finishes is the official classification by
	 * each horse's best time. */
	UPROPERTY() TArray<FHRRaceRun> Runs;
	UPROPERTY() TArray<FHRIncident> Incidents;
	/** Simulated public: top-three orders over 200 replays, frozen at declaration. */
	UPROPERTY() TArray<FHROrderCount> PublicOrders;

	bool IsRun() const { return Status != TEXT("declared"); }
};

USTRUCT(BlueprintType)
struct FHRMeeting
{
	GENERATED_BODY()

	UPROPERTY() int32 T = 0;
	UPROPERTY() int32 EventIndex = 0;
	/** In running order. A Grand Prix final (and a tournament's barrages) is appended once its heats are run. */
	UPROPERTY() TArray<FHRRace> Races;
	/** Horse id -> rider id for the whole race day (heats, barrages and final). */
	UPROPERTY() TMap<FString, FString> Riders;
};

/** A win bet: the stake on one horse to win one race. */
USTRUCT(BlueprintType)
struct FHRTicket
{
	GENERATED_BODY()

	UPROPERTY() FString Id;
	UPROPERTY() FString PlayerId;
	UPROPERTY() int32 T = 0;
	UPROPERTY() FString RaceKey;
	UPROPERTY() FString HorseId;
	UPROPERTY() int32 Stake = 0;
	/** "open", "won", "lost" or "refunded". */
	UPROPERTY() FString Status;
	UPROPERTY() int32 Payout = 0;
	/** Odds paid per coin, fixed when the race was run. */
	UPROPERTY() double Rapport = 0;
};

/** A horse offered by one stable to the others. */
USTRUCT(BlueprintType)
struct FHRSaleListing
{
	GENERATED_BODY()

	UPROPERTY() FString HorseId;
	UPROPERTY() FString SellerId;
	UPROPERTY() int32 Price = 0;
	UPROPERTY() int32 SinceT = 0;
};

/** A mare in foal: the foal is born DueT and belongs to the stable that arranged the breeding. */
USTRUCT(BlueprintType)
struct FHRPregnancy
{
	GENERATED_BODY()

	UPROPERTY() FString MareId;
	UPROPERTY() FString SireId;
	UPROPERTY() FString BreederId;
	UPROPERTY() int32 ConceivedT = 0;
	UPROPERTY() int32 DueT = 0;
	/** The name the player chose for the foal ("" = a drawn name). */
	UPROPERTY() FString FoalName;
};

/** World news: births, sales, breeding, retirements, injuries, titles, transfers. */
USTRUCT(BlueprintType)
struct FHRNews
{
	GENERATED_BODY()

	UPROPERTY() int32 T = 0;
	/** "birth", "sale", "purchase", "breeding", "retire", "injury", "title", "listing", "result", "upset", "rider",
	 * "transfer", "debt" or "arrival". */
	UPROPERTY() FString Kind;
	UPROPERTY() FString Text;
	UPROPERTY() TArray<FString> HorseIds;
	UPROPERTY() TArray<FString> StableIds;
};

/** One player of the world, identified by an opaque id the game chooses: a bettor, and the owner of a stable once bought. */
USTRUCT(BlueprintType)
struct FHRPlayer
{
	GENERATED_BODY()

	UPROPERTY() FString Id;
	UPROPERTY() FString Name;
	UPROPERTY() int32 Coins = 160;
	UPROPERTY() int32 TotalStaked = 0;
	UPROPERTY() int32 TotalWon = 0;
	UPROPERTY() int32 TicketsWon = 0;
	/** Daily income received since arrival. */
	UPROPERTY() int32 TotalIncome = 0;
	/** As an owner: the player rides the stable's runners rather than its riders. */
	UPROPERTY() bool bRides = true;
	/** As an owner: horses kept out of the next race day. */
	UPROPERTY() TArray<FString> Resting;
	/** The player's rider skill per race stage (as FHRRider::Skill; empty = a beginner). It grows with every race ridden
	 * and every training session. */
	UPROPERTY() TArray<int32> RiderSkill;
	UPROPERTY() int32 Rides = 0;
	/** As an owner: horses trained on day TrainedT (one session per horse per day). */
	UPROPERTY() TArray<FString> Trained;
	UPROPERTY() int32 TrainedT = -1;
};

USTRUCT(BlueprintType)
struct FHRWorldState
{
	GENERATED_BODY()

	UPROPERTY() int32 SchemaVersion = 1;
	UPROPERTY() FString RulesVersion;
	UPROPERTY() FString Seed;
	/** Unix time (seconds) of world second 0, set by the host (HRRules::StartClock); 0 until then. */
	UPROPERTY() int64 EpochUnix = 0;
	/** The current race day. */
	UPROPERTY() int32 T = 0;
	/** Season number (one season = 12 race days = one in-game year). */
	UPROPERTY() int32 Edition = 1;
	/** The day the world opened to players (before it: the simulated earlier season). */
	UPROPERTY() int32 ArrivalT = 0;
	UPROPERTY() TArray<FHRStable> Stables;
	UPROPERTY() TMap<FString, FHRHorse> Horses;
	UPROPERTY() FHRMeeting Meeting;
	UPROPERTY() TArray<FHRSaleListing> Listings;
	UPROPERTY() TArray<FHRPregnancy> Pregnancies;
	UPROPERTY() TArray<FHRTicket> Tickets;
	UPROPERTY() TArray<FHRNews> News;
	/** Player id -> player. */
	UPROPERTY() TMap<FString, FHRPlayer> Players;
	/** Every rider ever generated, retired ones included. */
	UPROPERTY() TMap<FString, FHRRider> Riders;
	/** Legend id -> first day it may appear again (one season after its retirement). */
	UPROPERTY() TMap<FString, int32> LegendCooldownUntil;
	UPROPERTY() int32 RiderSerial = 0;
	/** Monotonic counter for unique ids (tickets). */
	UPROPERTY() int32 Serial = 0;
};
