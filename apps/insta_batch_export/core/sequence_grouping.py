from datetime import timedelta


class SequenceRow:
    def __init__(self, label, date, items_by_pos, complete, missing_positions):
        self.label = label
        self.date = date
        self.items_by_pos = items_by_pos
        self.complete = complete
        self.missing_positions = missing_positions

    def __repr__(self):
        return (
            "SequenceRow(label=%r, complete=%r, missing_positions=%r)"
            % (self.label, self.complete, self.missing_positions)
        )


def group_sequences(items_by_pos, tolerance_seconds=3):
    positions = list(items_by_pos.keys())
    events = []
    for pos, items in items_by_pos.items():
        for item in items:
            events.append((item.timestamp, pos, item))

    events.sort(key=lambda event: (event[0], event[1], event[2].basename))
    rows = []
    tolerance = timedelta(seconds=tolerance_seconds)

    for timestamp, pos, item in events:
        best_cluster = None
        best_delta = None
        for cluster in rows:
            if pos in cluster["_items_by_pos"]:
                continue
            delta = abs(timestamp - cluster["_anchor"])
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                best_cluster = cluster
                best_delta = delta

        if best_cluster is None:
            rows.append({"_anchor": timestamp, "_items_by_pos": {pos: item}})
        else:
            best_cluster["_items_by_pos"][pos] = item

    sequence_rows = []
    for cluster in rows:
        items_for_row = dict(cluster["_items_by_pos"])
        missing_positions = [pos for pos in positions if pos not in items_for_row]
        anchor = min(item.timestamp for item in items_for_row.values())
        sequence_rows.append(
            SequenceRow(
                label=anchor.strftime("%Y%m%d_%H%M%S"),
                date=anchor.strftime("%Y-%m-%d"),
                items_by_pos=items_for_row,
                complete=len(missing_positions) == 0,
                missing_positions=missing_positions,
            )
        )

    sequence_rows.sort(key=lambda row: row.label)
    return sequence_rows
