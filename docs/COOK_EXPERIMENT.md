# Cook experiment status

Modern incremental cooking is an opt-in development experiment. It is not approved as a production default,
and it has no complete packaged-correctness acceptance or established end-to-end speedup. Normal cooking
defaults remain unchanged. Use the [normal build workflow](INCREMENTAL_BUILDS.md).

The CLI retains `--cook-mode modern-incremental` and `modern-full` for separately planned development work.
These modes forward UE 5.8 dependency-tracking flags through the existing guarded UAT command. They do not
skip compilation, change the three compiler workers or reduce package scope. Their cook observations report
requested and effective modes; a requested incremental cook can legitimately fall back to full.

An experimental receipt always retains `native_parity: false`. A successful command, archive checksum or
skip count does not prove that packaged content is correct. No prior private fixture, patch bundle or
measurement script is a supported setup procedure. The old acceptance walkthrough has been removed.

Any future evaluation needs its own bounded question and reviewed inputs before native work begins. It must
preserve normal admission, guards, source fingerprints and shared caches. This page schedules no further work.
