"""The SAM template (schedules, env) and config/sources.yaml must agree: the template cannot read the file, so a test does."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: (
    loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else
    loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)))


def template():
    return yaml.load((ROOT / "platform-iac/lambda/template.yaml").read_text(encoding="utf-8"), Loader=_Loader)


def test_schedules_match_sources_file():
    sources = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))["sources"]
    events = template()["Resources"]["ConnectorFunction"]["Properties"]["Events"]
    scheduled = {}
    for ev in events.values():
        if ev["Type"] != "ScheduleV2":
            continue
        import json
        src = json.loads(ev["Properties"]["Input"])["source"]
        scheduled[src] = int(re.search(r"rate\((\d+) minutes\)", ev["Properties"]["ScheduleExpression"]).group(1))
    for name, body in sources.items():
        if body.get("enabled", True):
            assert scheduled.get(name) == body["interval_minutes"], f"{name}: template and sources.yaml disagree"
        else:
            assert name not in scheduled, f"{name} is disabled in sources.yaml but scheduled in the template"


def test_pipeline_function_reads_the_shipped_config_dirs():
    env = template()["Resources"]["PipelineFunction"]["Properties"]["Environment"]["Variables"]
    assert env["USEP_POLICY_DIR"] == "config/runtime"
    assert (ROOT / "config/runtime/classification.yaml").is_file()


def test_every_notification_targets_a_queue_with_a_policy_and_dead_letter_queue():
    res = template()["Resources"]
    confs = res["DataBucket"]["Properties"]["NotificationConfiguration"]["QueueConfigurations"]
    prefixes = [c["Filter"]["S3Key"]["Rules"][0]["Value"] for c in confs]
    assert len(prefixes) == len(set(prefixes)) and {"bus/raw.", "bus/tombstone.", "bus/entity.", "bus/evidence."} == set(prefixes)
    assert not any(a != b and (a.startswith(b)) for a in prefixes for b in prefixes)          # S3 rejects overlapping prefixes
    for c in confs:
        qname = c["Queue"][0] if isinstance(c["Queue"], list) else c["Queue"]          # "<Queue>.Arn" from !GetAtt
        qname = qname.split(".")[0]
        assert qname in res and res[qname]["Type"] == "AWS::SQS::Queue", qname
        assert res[qname]["Properties"]["RedrivePolicy"]["maxReceiveCount"] >= 1
        assert f"{qname}Policy" in res and f"{qname}Policy" in res["DataBucket"]["DependsOn"] or qname == "RawEventQueue"
    assert "RawEventQueuePolicy" in res["DataBucket"]["DependsOn"]


def test_webhook_function_can_only_invoke_the_connector_and_is_throttled():
    fn = template()["Resources"]["WebhookFunction"]["Properties"]
    assert fn["Handler"] == "webhook_handler.handler" and fn["ReservedConcurrentExecutions"] <= 10
    assert fn["Events"]["Webhook"]["Properties"]["Path"] == "/webhook/{source}"
