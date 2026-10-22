# Threat model

Actors: hospital sites (data holders), the aggregation server, other participating sites, users of the released model,
and network attackers. The baseline assumption is an honest-but-curious server and sites: they follow the protocol but try to learn more.

| Mechanism | Protects against | Does NOT protect against | Guarantee in FedCardio |
|---|---|---|---|
| Federated learning (no PET) | Raw-record transfer; central data store | Server or eavesdropper reconstructing records from updates (we show exact single-record recovery for LR, `results/p2_attacks.csv`) | None formal |
| **Paper SVT filter** (re-implemented) | Some update leakage, heuristically | No composition over rounds, so no end-to-end bound | None formal (`ε` is per release only) |
| **DP-SGD** (record-level, local to each site, RDP accountant) | Inference about any single patient from the updates *and* from the released model (membership inference, reconstruction) | Population-level inferences; a malicious server deviating from the protocol; poor utility at small ε | (ε, δ) per site over all rounds, e.g. ε=3, δ=1e-5 |
| **CKKS homomorphic encryption** | Server seeing any individual update (it only sees ciphertexts) | What the decrypted global model reveals; colluding key holders; malicious clients | Confidentiality of updates vs. the server (key held by clients only) |
| **Secure aggregation** (additive masking) | Server seeing individual updates (only the sum is revealed) | Released model leakage; dropout recovery is not implemented; a malicious server | Same as HE against an honest-but-curious server, at ~1× bandwidth |
| TLS / mTLS + Flower node auth | Network eavesdropping and spoofed nodes | Compromised endpoints | Transport confidentiality and integrity |
| Envelope encryption + consent (record sharing) | Database theft; access without consent; access after revocation (key destroyed) | Recipient copying data they were allowed to see; the dev `FileKMS` stub is **insecure** | AES-256-GCM per record; per-hospital KEKs |
| Hash-chained audit log | Silent edits or deletions of audit history | An attacker who can rewrite the whole chain *and* the anchored head (anchor the head externally in production) | Tamper evidence |

Key point: **HE/SecAgg and DP solve different problems.** HE/SecAgg hide updates from the server. Only DP limits what
the released model reveals about individuals. In our membership-inference test, HE and SecAgg leak exactly as much as
plain FedAvg (same model). Valid combinations offered: `dpsgd+he`, `dpsgd+secagg`. SCAFFOLD + DP-SGD is rejected, because the
control variates are not privatised.
