"""Bounded compatibility diagnostics; arbitrary exception text is never logged."""
from atelier.harness import capacity_protocol as wire


KNOWN_REASONS = frozenset({
    'Authoritative OS boot identity unavailable',
    'Cannot establish the legacy write-open barrier',
    'Capacity activation changed',
    'Capacity cutover directory must be private and owned',
    'Capacity cutover is not active',
    'Capacity cutover is not sealed',
    'Capacity cutover policy differs from the reviewed broker policy',
    'Capacity file changed while reading',
    'Capacity file must be bounded, owned and regular',
    'Capacity lane ancestors cannot be symlinks',
    'Capacity lane changed during verification',
    'Capacity lane inode, seal or change identity was modified',
    'Capacity lane path must be absolute',
    'Capacity lane paths differ from the fixed compatibility barrier',
    'Capacity lanes must be owned single-link regular files',
    'Capacity paths cannot contain symlinks',
    'Cutover reserve exceeds total capacity',
    'Full capacity requires a verified new OS boot after sealing legacy lanes',
    'Full capacity requires the fixed machine compatibility paths',
    'Incomplete stable capacity volume UUID observation',
    'Invalid capacity integer',
    'Invalid capacity message',
    'Invalid capacity migration provenance',
    'Invalid capacity protocol fields',
    'Invalid capacity text',
    'Invalid cutover activation or boot identity',
    'Invalid cutover policy or endpoint',
    'Invalid stable capacity volume UUID',
    'Legacy cutover seal requires explicit volume migration and another OS boot',
    'Legacy write-open is still permitted, including through an ACL',
    'Maintenance prior-boot migration evidence differs from the sealed policy',
    'Maintenance requires a verified current-boot seal',
    'Maintenance requires archived prior-boot volume migration evidence',
    'Maintenance requires the original sealed policy digest',
    'Prior-boot closure requires a positive OS boot change',
    'Prior-boot migration proof differs from the archived seals',
    'Prior-boot provenance requires a schema3 active record',
    'Shared capacity lock belongs to a replaced lane inode',
    'Stable capacity volume UUID observation failed',
    'Stable capacity volume UUID observation is unavailable',
    'Unsupported capacity cutover record',
    'Unsupported prior-boot promotion proof',
})


def failure_reason(error):
    """@cc [owner:fontanierh,label:security] compatibility-diagnostic-redaction
    Compatibility logs MUST emit only exact allowlisted static failure messages. Unknown errors,
    including OSError paths and arbitrary CapacityError text, MUST use a generic reason.
    """
    reason = str(error) if isinstance(error, wire.CapacityError) else None
    return reason if reason in KNOWN_REASONS else 'Unclassified compatibility verification failure'
