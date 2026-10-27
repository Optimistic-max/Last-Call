# Tests for conditions.py: D1-D7 from docs/TEST_PLAN.md, plus the name cleanup.
# Plain lists of names only: no database, no PayPal, no clock. All names are made up.

import random

import conditions


# A short way to write one pledge: pledge("Ana", "Jay") means "Ana, only if Jay's in".
# *needs collects any number of names into a list.
def pledge(name, *needs):
    return {"name": name, "conditions": list(needs)}


# D1: a chain where the last link is missing. A needs B, B needs C, and C never pledged.
# B drops first, which breaks A's condition, so A drops on the next pass. Nobody is counted.
def test_d1_chain_with_missing_link_all_drop():
    pledges = [pledge("A", "B"), pledge("B", "C")]
    assert conditions.counted_pledges(pledges) == []


# D2: a mutual circle, "in if you're in". Both count (D06).
def test_d2_mutual_circle_both_in():
    pledges = [pledge("Ana", "Jay"), pledge("Jay", "Ana")]
    assert conditions.counted_pledges(pledges) == ["Ana", "Jay"]


# D3: a circle plus someone who depends on it. A <-> B, and C needs A. All three count.
def test_d3_circle_plus_dependent_all_in():
    pledges = [pledge("A", "B"), pledge("B", "A"), pledge("C", "A")]
    assert conditions.counted_pledges(pledges) == ["A", "B", "C"]


# D4: a condition naming someone who never pledged. Only that pledge drops.
def test_d4_unknown_name_drops_only_that_pledge():
    pledges = [pledge("Ana", "Kim"), pledge("Jay"), pledge("Sam")]
    assert conditions.counted_pledges(pledges) == ["Jay", "Sam"]


# D5: two conditions on one pledge. Both are needed, not just one.
def test_d5_two_conditions_both_needed():
    only_jay = [pledge("Ana", "Jay", "Kim"), pledge("Jay")]
    assert conditions.counted_pledges(only_jay) == ["Jay"]
    jay_and_kim = [pledge("Ana", "Jay", "Kim"), pledge("Jay"), pledge("Kim")]
    assert conditions.counted_pledges(jay_and_kim) == ["Ana", "Jay", "Kim"]


# D6: names match ignoring case and extra spaces, and come back spelled as given.
def test_d6_names_match_ignoring_case_and_spaces():
    pledges = [pledge("  JAY  ", "ana lee"), pledge("Ana   Lee", "jay")]
    assert conditions.counted_pledges(pledges) == ["  JAY  ", "Ana   Lee"]


# D6: the cleanup itself. tidy_name is how names are saved; name_key is how they are matched.
def test_d6_tidy_name_and_name_key():
    assert conditions.tidy_name("  Ana   Lee ") == "Ana Lee"
    assert conditions.name_key("  ANA   lee ") == "ana lee"


# D7 (invariant 1 in STATE_MACHINE.md), by hand: Ana needs Jay, so she isn't counted until Jay
# joins. Jay joining adds Ana and removes nobody.
def test_d7_joining_example():
    before = [pledge("Ana", "Jay"), pledge("Sam")]
    after = before + [pledge("Jay")]
    assert conditions.counted_pledges(before) == ["Sam"]
    assert conditions.counted_pledges(after) == ["Ana", "Sam", "Jay"]


# Make a random group for D7: each person has 0 to 2 conditions, naming people from a bigger list
# of names, so some conditions name someone who never pledged. Conditions on yourself can happen too.
def random_group(generator, size):
    all_names = ["Ana", "Jay", "Kim", "Sam", "Lee", "Max", "Ivy", "Ola", "Raj", "Zoe"]
    group = []
    for name in generator.sample(all_names, size):
        needs = generator.sample(all_names, generator.randint(0, 2))
        group.append(pledge(name, *needs))
    return group, all_names


# D7: 2,000 random groups. Adding one more pledger (who may have conditions too) never removes
# anyone who was counted before. A fixed seed gives the same groups every run.
def test_d7_joining_never_uncounts_anyone():
    generator = random.Random(7)
    for _ in range(2000):
        group, all_names = random_group(generator, generator.randint(0, 8))
        names_in_group = []
        for person in group:
            names_in_group.append(person["name"])
        names_not_in_group = []
        for name in all_names:
            if name not in names_in_group:
                names_not_in_group.append(name)
        newcomer_name = generator.choice(names_not_in_group)
        newcomer = pledge(newcomer_name, *generator.sample(all_names, generator.randint(0, 2)))
        before = conditions.counted_pledges(group)
        after = conditions.counted_pledges(group + [newcomer])
        for name in before:
            assert name in after


# A condition naming yourself is met. A blank condition matches nobody, so that pledge drops.
def test_self_condition_counts_and_blank_condition_drops():
    assert conditions.counted_pledges([pledge("Ana", "ana")]) == ["Ana"]
    assert conditions.counted_pledges([pledge("Ana", "  "), pledge("Jay")]) == ["Jay"]


# No pledges means nobody counted.
def test_no_pledges():
    assert conditions.counted_pledges([]) == []
