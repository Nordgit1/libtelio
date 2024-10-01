use futures::future::BoxFuture;
use std::fmt::Debug;
use std::hash::Hash;
use std::{collections::HashMap, sync::Arc};

use telio_utils::{telio_log_debug, telio_log_warn};
use tokio;
use tokio::time::sleep_until;

type Action<V, R = std::result::Result<(), ()>> =
    Arc<dyn for<'a> Fn(&'a mut V) -> BoxFuture<'a, R> + Sync + Send>;

/// When batcher is evaluating actions, how far in the past the triggered signal should be taken into an effect
const TRIGGER_EFFECTIVE_DURATION: tokio::time::Duration = tokio::time::Duration::from_secs(5);

/// Trigger logic throttle value, for safety.
const TRIGGER_SAFETY_THROTTLE: tokio::time::Duration = tokio::time::Duration::from_secs(2);

/// Batcher works by being queried for actions to get. An explicit call is needed to go into the
/// polling state to execute the actions.
pub struct Batcher<K, V> {
    actions: HashMap<K, (BatchEntry, Action<V>)>,

    /// If while polling a new peer is added, batcher needs to
    /// handle that and does so through a `notify_add` notification. Peers deadline is set to
    /// immediate, so no timestamp keeping is required, the future will immediately resolve
    notify_add: tokio::sync::Notify,

    // If while polling triggering happens, a notification is issued, else timestamp is stored to
    // detect the trigger.
    notify_trigger_last_timestamp: tokio::time::Instant,
    notify_trigger_timestamp: Option<tokio::time::Instant>,
    notify_trigger: tokio::sync::Notify,
}

struct BatchEntry {
    deadline: tokio::time::Instant,
    interval: std::time::Duration,
    threshold: std::time::Duration,
}

impl<K, V> Default for Batcher<K, V>
where
    K: Eq + Hash + Send + Sync + Debug + Clone,
{
    fn default() -> Self {
        Self::new()
    }
}

impl<K, V> Batcher<K, V>
where
    K: Eq + Hash + Send + Sync + Debug + Clone,
{
    pub fn new() -> Self {
        Self {
            actions: HashMap::new(),
            notify_add: tokio::sync::Notify::new(),
            notify_trigger: tokio::sync::Notify::new(),
            notify_trigger_timestamp: None,
            notify_trigger_last_timestamp: tokio::time::Instant::now()
                - tokio::time::Duration::from_secs(60 * 60 * 24),
        }
    }

    /// Batching works by sleeping until the nearest future and then trying to batch more actions
    /// based on the threshold value. Higher delay before calling the function will increase the chances of batching
    /// because the deadlines will _probably_ be in the past already.
    /// Adding a new action or explicit trigger wakes up the batcher for immediate attempt to trigger
    pub async fn get_actions(&mut self) -> Vec<(K, Action<V>)> {
        let mut batched_actions: Vec<(K, Action<V>)> = vec![];

        loop {
            if !self.actions.is_empty() {
                let actions = &mut self.actions;
                let mut triggered = false;
                {
                    if let Some(trig_ts) = self.notify_trigger_timestamp {
                        if tokio::time::Instant::now() - trig_ts < TRIGGER_EFFECTIVE_DURATION {
                            self.notify_trigger_timestamp = None;
                            triggered = true;
                        }
                    }
                }

                // Safety mechanism
                if triggered {
                    let now = tokio::time::Instant::now();
                    let timediff = now - self.notify_trigger_last_timestamp;
                    self.notify_trigger_last_timestamp = now;

                    if timediff < TRIGGER_SAFETY_THROTTLE {
                        telio_log_warn!("Batcher triggers too often. Time passed since last one: {}ms. Reverting the trigger", timediff.as_millis());
                        triggered = false;
                    }
                }

                if !triggered {
                    if let Some(closest_entry) =
                        actions.values().min_by_key(|entry| entry.0.deadline)
                    {
                        tokio::select! {
                            _ = self.notify_add.notified() => {
                                // Item was added, we need to immediately emit it
                            }
                            _ = sleep_until(closest_entry.0.deadline) => {
                                // Closest action should now be emitted
                            }
                            // we received a premature batch trigger
                            _ = self.notify_trigger.notified() => {
                                // trigger notification
                            }
                        }
                    }
                }

                let now = tokio::time::Instant::now();
                for (key, action) in actions.iter_mut() {
                    let adjusted_action_deadline = now + action.0.threshold;

                    if action.0.deadline <= adjusted_action_deadline {
                        action.0.deadline = now + action.0.interval;
                        batched_actions.push((key.clone(), action.1.clone()));
                    }
                }

                return batched_actions;
            } else {
                // in case we have no actions, we block until we will add one. Returning early will
                // trigger a tight loop
                tokio::select! {
                    _ = self.notify_add.notified() => {}
                }
            }
        }
    }
    /// Remove batcher action. Action is no longer eligible for batching
    pub fn remove(&mut self, key: &K) {
        telio_log_debug!("removing item from batcher with key({:?})", key);
        self.actions.remove(key);
    }

    /// Trigger batcher manually. Triggering will try to batch the events at the a given time. It
    /// doesn't mean it will find anything to batch if a proper threshold is set.
    pub fn trigger(&mut self) {
        telio_log_debug!("triggering batcher");
        self.notify_trigger_timestamp = Some(tokio::time::Instant::now());
        self.notify_trigger.notify_waiters();
    }

    /// Add batcher action. Batcher itself doesn't run the tasks and depends
    /// on actions being manually invoked. Adding an action immediately triggers it
    /// thus if the call site awaits for the future then it will resolve immediately after this
    /// function call.
    pub fn add(
        &mut self,
        key: K,
        interval: std::time::Duration,
        threshold: std::time::Duration,
        action: Action<V>,
    ) {
        telio_log_debug!(
            "adding item to batcher with key({:?}), interval({:?}), threshold({:?})",
            key,
            interval,
            threshold,
        );

        let mut threshold = threshold;
        if threshold >= interval {
            threshold = interval / 2;
            telio_log_warn!(
                "Threshold should not be bigger than the interval. Overriden to ({:?})",
                threshold
            );
        }

        let entry = BatchEntry {
            deadline: tokio::time::Instant::now(),
            interval,
            threshold,
        };

        self.actions.insert(key, (entry, action));
        self.notify_add.notify_waiters();
    }

    pub fn get_interval(&self, key: &K) -> Option<u32> {
        self.actions
            .get(key)
            .and_then(|(entry, _)| entry.interval.as_secs().try_into().ok())
    }
}

/// Tests provide near-perfect immediate sleeps due to how tokio runtime acts when it's paused(basically sleeps are resolved immediately)
#[cfg(test)]
mod tests {

    pub struct TestChecker {
        values: Vec<(String, tokio::time::Instant)>,
    }

    use std::{sync::Arc, time::Duration};

    use futures::stream::FuturesUnordered;

    use crate::batcher::Batcher;

    #[tokio::test(start_paused = true)]
    async fn batch_and_trigger() {
        let start_time = tokio::time::Instant::now();
        let mut batcher = Batcher::<String, TestChecker>::new();

        batcher.add(
            "key0".to_owned(),
            Duration::from_secs(100),
            Duration::from_secs(50),
            Arc::new(|s: _| {
                Box::pin(async move {
                    s.values
                        .push(("key0".to_owned(), tokio::time::Instant::now()));
                    Ok(())
                })
            }),
        );

        let mut test_checker = TestChecker { values: Vec::new() };

        // pick up the immediate fires
        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }
        assert!(test_checker.values.len() == 1);

        let get_checkpoint =
            |add: u64| tokio::time::Instant::now() + tokio::time::Duration::from_secs(add);

        let mut checkpoints = vec![
            get_checkpoint(10),
            get_checkpoint(20),
            get_checkpoint(60),
            get_checkpoint(90),
            get_checkpoint(200),
            get_checkpoint(270),
            get_checkpoint(280),
            get_checkpoint(730),
            get_checkpoint(1000),
        ];

        use tokio::time::sleep_until;
        loop {
            tokio::select! {
                _ = tokio::time::advance(tokio::time::Duration::from_secs(1)) => {
            }

                _ = sleep_until(checkpoints[0]) => { batcher.trigger(); checkpoints.remove(0); if checkpoints.len() == 0 {break} }

                actions = batcher.get_actions() => {
                    for ac in &actions {
                        ac.1(&mut test_checker).await.unwrap();
                    }
                }
            }
        }

        fn round_duration_to_nearest_10_secs(duration: Duration) -> Duration {
            let seconds =
                duration.as_secs() as f64 + duration.subsec_nanos() as f64 / 1_000_000_000.0;
            let rounded = (seconds / 10.0).round() * 10.0;
            Duration::from_secs(rounded as u64)
        }

        let key0_entries: Vec<tokio::time::Duration> = test_checker
            .values
            .iter()
            .filter(|e| e.0 == "key0")
            .map(|e| round_duration_to_nearest_10_secs(e.1.duration_since(start_time)))
            .collect();

        let expected_diff_values: Vec<Duration> =
            vec![0, 60, 160, 260, 360, 460, 560, 660, 730, 830, 930]
                .iter()
                .map(|v| tokio::time::Duration::from_secs(*v))
                .collect();
        assert!(
            key0_entries == expected_diff_values,
            "expected: {:?}, got: {:?}",
            expected_diff_values,
            key0_entries
        );
    }

    #[tokio::test(start_paused = true)]
    async fn batch_one() {
        let start_time = tokio::time::Instant::now();
        let mut batcher = Batcher::<String, TestChecker>::new();
        batcher.add(
            "key".to_owned(),
            Duration::from_secs(100),
            Duration::from_secs(0),
            Arc::new(|s: _| {
                Box::pin(async move {
                    s.values
                        .push(("key".to_owned(), tokio::time::Instant::now()));
                    Ok(())
                })
            }),
        );

        let mut test_checker = TestChecker { values: Vec::new() };

        // pick up the immediate fire
        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }
        assert!(test_checker.values.len() == 1);

        // pick up the second event
        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }

        assert!(test_checker.values.len() == 2);

        assert!(test_checker.values[0].1.duration_since(start_time) == Duration::from_secs(0));
        assert!(test_checker.values[1].1.duration_since(start_time) == Duration::from_secs(100));

        // after a pause of retrieving actions there will be a delay in signals as well as they are not active on their own
        tokio::time::advance(Duration::from_secs(550)).await;
        assert!(test_checker.values.len() == 2);

        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }

        assert!(test_checker.values.len() == 3);
        assert!(test_checker.values[2].1.duration_since(start_time) == Duration::from_secs(650));
    }

    #[tokio::test(start_paused = true)]
    async fn batch_two_with_threshold_and_delay() {
        let start_time = tokio::time::Instant::now();
        let mut batcher = Batcher::<String, TestChecker>::new();
        batcher.add(
            "key0".to_owned(),
            Duration::from_secs(100),
            Duration::from_secs(50),
            Arc::new(|s: _| {
                Box::pin(async move {
                    s.values
                        .push(("key0".to_owned(), tokio::time::Instant::now()));
                    Ok(())
                })
            }),
        );

        tokio::time::advance(Duration::from_secs(30)).await;

        batcher.add(
            "key1".to_owned(),
            Duration::from_secs(100),
            Duration::from_secs(50),
            Arc::new(|s: _| {
                Box::pin(async move {
                    s.values
                        .push(("key1".to_owned(), tokio::time::Instant::now()));
                    Ok(())
                })
            }),
        );

        // At this point there are two actions added, one at t(0) and another at t(30).
        let mut test_checker = TestChecker { values: Vec::new() };

        // pick up the immediate fires
        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }
        assert!(test_checker.values.len() == 2);

        // Do again and batching should be in action since the threshold of the second signal is bigger(50) than the delay between the packets(30)
        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }

        assert!(test_checker.values.len() == 4);

        let key0_entries: Vec<tokio::time::Duration> = test_checker
            .values
            .iter()
            .filter(|e| e.0 == "key0")
            .map(|e| e.1.duration_since(start_time))
            .collect();
        let key1_entries: Vec<tokio::time::Duration> = test_checker
            .values
            .iter()
            .filter(|e| e.0 == "key1")
            .map(|e| e.1.duration_since(start_time))
            .collect();

        // Immediate fires were supressed because we need to poll them and we did so only after 30seconds
        // Thus everything will be aligned at 30seconds

        assert!(key0_entries[0] == Duration::from_secs(30));
        assert!(key1_entries[0] == Duration::from_secs(30));

        assert!(key0_entries[1] == Duration::from_secs(130));
        assert!(key1_entries[1] == Duration::from_secs(130));
    }

    #[tokio::test(start_paused = true)]
    async fn batch_two_no_threshold_delayed_check() {
        let _start_time = tokio::time::Instant::now();
        let mut batcher = Batcher::<String, TestChecker>::new();
        batcher.add(
            "key0".to_owned(),
            Duration::from_secs(100),
            Duration::from_secs(0),
            Arc::new(|s: _| {
                Box::pin(async move {
                    s.values
                        .push(("key0".to_owned(), tokio::time::Instant::now()));
                    Ok(())
                })
            }),
        );

        tokio::time::advance(Duration::from_secs(30)).await;

        batcher.add(
            "key1".to_owned(),
            Duration::from_secs(100),
            Duration::from_secs(0),
            Arc::new(|s: _| {
                Box::pin(async move {
                    s.values
                        .push(("key1".to_owned(), tokio::time::Instant::now()));
                    Ok(())
                })
            }),
        );

        // At this point there are two actions added, one at t(0) and another at t(30).
        let mut test_checker = TestChecker { values: Vec::new() };

        // pick up the immediate fire
        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }
        assert!(
            test_checker.values.len() == 2,
            "Both actions should be emitted immediately"
        );

        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }

        assert!(test_checker.values.len() == 4, "Even though there was no threshold and actions were added at different times, we query only after adding the second one which resets both deadlines and aligns them");
    }

    #[tokio::test(start_paused = true)]
    async fn batch_two_no_threshold_nodelay_check() {
        let start_time = tokio::time::Instant::now();
        let mut batcher = Batcher::<String, TestChecker>::new();
        batcher.add(
            "key0".to_owned(),
            Duration::from_secs(100),
            Duration::from_secs(0),
            Arc::new(|s: _| {
                Box::pin(async move {
                    s.values
                        .push(("key0".to_owned(), tokio::time::Instant::now()));
                    Ok(())
                })
            }),
        );

        let mut test_checker = TestChecker { values: Vec::new() };
        // pick up the immediate fire
        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }
        assert!(test_checker.values.len() == 1);

        tokio::time::advance(Duration::from_secs(30)).await;

        batcher.add(
            "key1".to_owned(),
            Duration::from_secs(100),
            Duration::from_secs(0),
            Arc::new(|s: _| {
                Box::pin(async move {
                    s.values
                        .push(("key1".to_owned(), tokio::time::Instant::now()));
                    Ok(())
                })
            }),
        );

        // pick up the immediate fire from the second action
        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }
        assert!(test_checker.values.len() == 2);

        for ac in batcher.get_actions().await {
            ac.1(&mut test_checker).await.unwrap();
        }

        assert!(
            test_checker.values.len() == 3,
            "No threshold but a delay was given, thus one signal should have resolved"
        );

        test_checker.values = vec![];
        for _ in 0..12 {
            for ac in batcher.get_actions().await {
                ac.1(&mut test_checker).await.unwrap();
            }
        }

        let key0sum: tokio::time::Duration = test_checker
            .values
            .iter()
            .filter(|e| e.0 == "key0")
            .map(|e| e.1.duration_since(start_time))
            .collect::<Vec<Duration>>()
            .windows(2)
            .map(|w| w[1] - w[0])
            .sum();

        let key1sum: tokio::time::Duration = test_checker
            .values
            .iter()
            .filter(|e| e.0 == "key1")
            .map(|e| e.1.duration_since(start_time))
            .collect::<Vec<Duration>>()
            .windows(2)
            .map(|w| w[1] - w[0])
            .sum();

        // Because of misalignment, each call produces only one action instead of both
        assert!(key0sum == Duration::from_secs(500));
        assert!(key1sum == Duration::from_secs(500));

        // Now let's wait a bit so upon iterating again signals would be aligned
        test_checker.values = vec![];
        tokio::time::advance(tokio::time::Duration::from_secs(500)).await;
        for _i in 0..11 {
            for ac in batcher.get_actions().await {
                ac.1(&mut test_checker).await.unwrap();
            }
        }

        let key0sum: tokio::time::Duration = test_checker
            .values
            .iter()
            .filter(|e| e.0 == "key0")
            .map(|e| e.1.duration_since(start_time))
            .collect::<Vec<Duration>>()
            .windows(2)
            .map(|w| w[1] - w[0])
            .sum();

        let key1sum: tokio::time::Duration = test_checker
            .values
            .iter()
            .filter(|e| e.0 == "key1")
            .map(|e| e.1.duration_since(start_time))
            .collect::<Vec<Duration>>()
            .windows(2)
            .map(|w| w[1] - w[0])
            .sum();

        assert!(key0sum == Duration::from_secs(1000));
        assert!(key1sum == Duration::from_secs(1000));
    }
}
