#pragma once
#include "CoreMinimal.h"

/**
 * Who a racing player is (docs/RACING.md, "Players"). Every install keeps one random id, generated once and saved beside
 * its racing world (Saved/racing/player-id.txt): 32 hexadecimal digits, no personal data and no secret. The host's own
 * player is "local:<id>". A guest presents its install's id when it joins (URacingWallet::ServerIdentify) and the host
 * keys its racing player "guest:<id>", so a returning guest finds its wallet, open bets and stable again. Guest keys
 * never collide with the host's: a guest cannot claim the host's player, even from the same install.
 *
 * The id is not authentication. A friend who copies another's id is that player on this host: acceptable for V1's LAN
 * and friends' sessions, where the host chooses whom to let in.
 *
 * A guest whose id is not valid, or is already held by another connected player, gets a session player
 * ("session:<session player id>"): a wallet for this session only, never saved, and no stable.
 */
namespace RacingIdentity
{
    inline const TCHAR* const HostPrefix = TEXT("local:");
    inline const TCHAR* const GuestPrefix = TEXT("guest:");
    inline const TCHAR* const SessionPrefix = TEXT("session:");
    /** An install id's length: an FGuid's 32 hexadecimal digits. */
    inline constexpr int32 InstallIdChars = 32;

    YORIMICHI_API bool IsValidInstallId(const FString& Id);
    YORIMICHI_API FString NewInstallId();
    /** The install id in player-id.txt's text ("local:<id>", or the bare id), empty when it holds none. */
    YORIMICHI_API FString ParseFile(const FString& Text);
    /** The install id saved at Path, generated and saved there the first time (or when the file holds none). Never empty:
     *  when the file cannot be written the id lasts for this run only (bSaved false). */
    YORIMICHI_API FString LoadOrCreate(const FString& Path, bool* bSaved = nullptr);

    inline FString HostKey(const FString& InstallId) { return HostPrefix + InstallId; }
    inline FString GuestKey(const FString& InstallId) { return GuestPrefix + InstallId; }
    inline FString SessionKey(const FString& SessionPlayerId) { return SessionPrefix + SessionPlayerId; }
    inline bool IsHost(const FString& Key) { return Key.StartsWith(HostPrefix); }
    inline bool IsGuest(const FString& Key) { return Key.StartsWith(GuestPrefix); }
    inline bool IsSession(const FString& Key) { return Key.StartsWith(SessionPrefix); }
    /** A key the world keeps across sessions (the host's or a guest's), not a session player's. */
    inline bool IsPersistent(const FString& Key) { return IsHost(Key) || IsGuest(Key); }

    /**
     * The racing key a guest gets for the install id it presents: GuestKey(Presented), or a session player when the id
     * is not valid or Held (the keys of the other players connected now) already has it. Why says which, empty for a
     * guest key. A second player presenting an id in use never takes the first one's wallet or stable.
     */
    YORIMICHI_API FString ResolveGuest(const FString& Presented, const FString& SessionPlayerId, const TSet<FString>& Held,
        FString* Why = nullptr);
}
