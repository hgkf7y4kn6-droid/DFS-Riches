from app import play_rankings as pr



def test_dst_environment_rewards_slow_low_scoring_turnover_prone_matchups():
    games = [
        # A shootout: high total, both offenses implied high, fast, careful with the ball.
        {"away": "AAA", "home": "BBB", "total": 52.0, "away_implied": 27.0, "home_implied": 25.0,
         "tempo_ranks": {"AAA": 2, "BBB": 4}},
        # A slugfest: low total, CCC's offense implied for 14, slow, sack- and turnover-prone.
        {"away": "CCC", "home": "DDD", "total": 36.0, "away_implied": 14.0, "home_implied": 22.0,
         "tempo_ranks": {"CCC": 30, "DDD": 28}},
    ]
    offense = {"AAA": {"sack_rate": 0.05, "giveaways": 0.8}, "BBB": {"sack_rate": 0.06, "giveaways": 0.9},
               "CCC": {"sack_rate": 0.11, "giveaways": 2.1}, "DDD": {"sack_rate": 0.07, "giveaways": 1.2}}
    env = pr.dst_environment(games, offense)
    # DDD's defense faces CCC (implied 14, sack- and turnover-prone, slow game): the best DST spot.
    assert max(env, key=env.get) == "DDD"
    # The shootout's defenses are the worst DST spots -- the reverse of the skill-player view.
    assert sorted(env, key=env.get)[:2] == sorted(["AAA", "BBB"], key=env.get)
    # Missing offense stats count as average rather than breaking the score.
    assert set(pr.dst_environment(games)) == {"AAA", "BBB", "CCC", "DDD"}
