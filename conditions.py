# The circle rule: which pledges count toward the goal (D06). Owner: Malama.
# Pure: no database, no PayPal, no clock. lifecycle.py loads the pledges and their conditions,
# and passes them in.


# "  Ana   Lee " -> "Ana Lee": no spaces at the ends, single spaces inside.
# Names are saved this way (docs/DATA_MODEL.md), so the board shows what the person typed, tidied.
# split() with no argument splits on any run of spaces and drops the empty pieces.
def tidy_name(name):
    return " ".join(name.split())


# The form of a name used only for matching: tidied and lowercase, so "ANA  lee" matches "ana lee".
# lower() is the same rule as the lower(name) unique index in schema.sql, so Python and the
# database agree on who is the same person.
def name_key(name):
    return tidy_name(name).lower()


# Who is counted (D06): assume everyone is in, then remove anyone with a condition naming someone
# who isn't in, and repeat until nothing changes. Removing one person can break someone else's
# condition, which is why one pass isn't enough.
# pledges is a list like [{"name": "Ana", "conditions": ["Jay"]}, ...]. A pledge with several
# conditions needs all of them. Returns the counted names, spelled as given and in the same order
# as the input, so the caller's join order (needed for D13) is kept.
def counted_pledges(pledges):
    counted = set()
    for pledge in pledges:
        counted.add(name_key(pledge["name"]))

    something_changed = True
    while something_changed:
        something_changed = False
        for pledge in pledges:
            key = name_key(pledge["name"])
            if key in counted and not all_conditions_met(pledge["conditions"], counted):
                counted.remove(key)
                something_changed = True

    result = []
    for pledge in pledges:
        if name_key(pledge["name"]) in counted:
            result.append(pledge["name"])
    return result


# True if every name in conditions belongs to someone still counted. No conditions means True.
def all_conditions_met(conditions, counted):
    for condition in conditions:
        if name_key(condition) not in counted:
            return False
    return True
