"""
Treasury Pulse ML pipeline.

    script1_prepare  – fetch transactions/positions/thresholds from the DB,
                       clean, transform, compute counterparty risk R(t)
    script2_forecast – fit one Prophet model per entity, store the 30-day
                       forecast in the Forecast table and sync Alerts
    script3_whatif   – apply what-if shocks to the stored baseline and
                       return (and persist) the scenario result

All three are plain functions so they can be called from API views,
management commands or a shell.
"""
