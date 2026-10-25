#!/usr/bin/env python3
"""Pull the Sonniss GDC recordings the transport bank's train cues are cut from (make.py TRAIN_SPEC) into
~/.cache/atelier/sonniss/transport, md5-checked, with the combat library's downloader (combat/fetch.py). The bank's
other cues are synthesis or layer the combat masters, which combat/fetch.py restores.

PICKS lists (local name, archive item, path inside the item, md5, bytes), as in combat/fetch.py: Paul's choices
(2026-10-20, final: freerun departure, distant blast idle) and the coordinator's idle design. Local signal processing only (audio/SONNISS-LICENSE.txt).

Usage:  python3 fetch.py [--force]
"""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location('combat_fetch', Path(__file__).resolve().parent.parent / 'combat' / 'fetch.py')
combat = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(combat)
from atelier.paths import cache_dir  # noqa: E402  (combat/fetch.py put the studio on the path)

PICKS = [
 # roll (every coach, speed-scaled): Airborne Sound, Royal Hudson ride, a vendor loop
 ('roll_steam_ride.wav', 'sonniss-gdc-2019-game-audio-bundle-normalized',
  'Airborne Sound - Steam Train/Train,Steam,4-6-4,Royal Hudson,H1e Class,No 2860,Ride,Engine,Rail Clatter,Rhythmic,Constant,Sizzle,Loop.wav',
  '2fa5f8b6f2317bb75a4411570c610d49', 8047154),
 # start and effort: On The Fly Audio, a steam engine free-running on coal, accelerating (its clean first 16 s: the
 # build-up from departure, then a 12-beat loop for the rest of the acceleration)
 ('dep_steam_freerun.wav', 'sonniss-gdc-2020-game-audio-bundle-normalized',
  'On The Fly Audio - Steam Engines Real & Foley/Steamengine FREERUN coal accelerations and decelarations 02 airy thuds and aggressive pufs-OTFA.wav',
  '0307eafbbb23014cd12c52d26f0ba41a', 11580642),
 # idle: Airborne Sound, a distant steam blast, looped: the steam swelling over the last seconds of the braking
 ('idle_steam_blast_distant.wav', 'sonniss-gdc-2018-game-audio-bundle-normalized',
  'Airborne Sound - Variety 1 Sound Effects/Steam Blast,Tube or Pipe,Distant.wav',
  'ceb5092996944d0997650319aa48beb1', 2478016),
 # clack: single joint clacks, Detunized, contact mics on the rails of a passing train
 ('roll_ext_rails.wav', 'sonniss-gdc-2015-game-audio-bundle-normalized',
  'Detunized - PassingTrains/contact_mics_on_rails_01.wav',
  '004098874ae9ff40e03e9753cd63ec50', 14455036),
 # pass: On The Fly Audio, a steam train approaching through a tunnel and passing, for lineside listeners
 ('pass_steam_tunnel.wav', 'sonniss-gdc-2020-game-audio-bundle-normalized',
  'On The Fly Audio - Steam Engines Real & Foley/Steamtrain approach with steam whistle in tunnel low pitch and pass by - MKH8040SMK-OTFA.wav',
  'ccde4f73efcb75e506468a4a3d4b4987', 38112958),
 # brake: the arrival up to the stop. Tone Glow, mic on the locomotive
 ('arr_steam_loco.wav', 'sonniss-gdc-2019-game-audio-bundle-normalized',
  'Tone Glow Libraries - Steam Trains/Steam Train Arrival, Rail Clatter, Brakes Squeal, Idle, Mic on Locomotive.wav',
  '60535cf6bcd400c835265da8de64e1ad', 53088968),
 # hiss: the engine blowing off at the stop (its strongest blast)
 ('arr_steam_hiss.wav', 'sonniss-gdc-2019-game-audio-bundle-normalized',
  'The Sound Pack Tree - Trains/166000 - Steam Blasts.wav',
  'e4dbfe83ac311e45b9901d221f85e21b', 1998038),
 # depart: the Royal Hudson's whistle as the train moves off
 ('sig_steam_whistle.wav', 'sonniss-gdc-2019-game-audio-bundle-normalized',
  'Airborne Sound - Steam Train/Train,Steam,4-6-4,Royal Hudson,H1e Class,No 2860,Whistle,Engine POV,Tired - While moving.wav',
  '8e54e4ed6d5197ae534ab125e66cf5b3', 3623136),
 # doors: closing a few seconds before the departure
 ('sig_door_close.wav', 'sonniss-gdc-2024-game-audio-bundle-normalized',
  'Jake Fielding - Train Onboards/DOORHydr_Train Door Close_JF_Train Tracks .wav',
  'a14fd51592dd76a9fe366b809f82a0e2', 354544),
]


def main():
    combat.ROOT, combat.PICKS = cache_dir('sonniss', 'transport'), PICKS
    return combat.main()


if __name__ == '__main__':
    sys.exit(main())
