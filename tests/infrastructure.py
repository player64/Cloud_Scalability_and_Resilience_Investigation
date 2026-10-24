"""Check the deployed Product endpoint and baseline Auto Scaling Group."""

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

import boto3


OUTPUTS_FILE = (
    Path(__file__).resolve().parent.parent / "infra" / "outputs.json"
)


def read_terraform_output(outputs: dict, name: str) -> str:
    """Read a required string from Terraform's JSON output format."""
    value = outputs[name]["value"]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Terraform output {name!r} is empty")
    return value


def check_product_endpoint(alb_url: str) -> None:
    """Require an HTTP 200 response containing a populated Product object."""
    url = f"{alb_url.rstrip('/')}/productapi/products"
    request = Request(url, method="GET")
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise AssertionError(
                f"expected HTTP 200, received {response.status}"
            )
        products = json.load(response)

    if not isinstance(products, list) or not products:
        raise AssertionError("expected a non-empty JSON list of products")
    if not any(
        isinstance(product, dict)
        and type(product.get("id")) is int
        and product["id"] > 0
        and isinstance(product.get("name"), str)
        and bool(product["name"].strip())
        and isinstance(product.get("price"), (int, float))
        and not isinstance(product["price"], bool)
        and product["price"] > 0
        for product in products
    ):
        raise AssertionError("no product has a valid id, name and price")


def check_product_asg(asg_name: str) -> None:
    """Require exactly one healthy InService Product instance."""
    response = boto3.client("autoscaling").describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_name]
    )
    groups = response["AutoScalingGroups"]
    if len(groups) != 1 or groups[0]["AutoScalingGroupName"] != asg_name:
        raise AssertionError(f"Auto Scaling Group {asg_name!r} was not found")

    instances = groups[0]["Instances"]
    if len(instances) != 1:
        raise AssertionError(
            f"expected one Product instance, found {len(instances)}"
        )
    instance = instances[0]
    if (instance["LifecycleState"] != "InService"
            or instance["HealthStatus"] != "Healthy"):
        raise AssertionError(
            f"instance {instance['InstanceId']} is "
            f"{instance['LifecycleState']}/{instance['HealthStatus']}"
        )


def check_product_post(alb_url: str) -> None:
    """Create a Product through the ALB and check the returned record."""
    product = {
        "name": f"Acceptance test {uuid4().hex}",
        "description": "Product POST acceptance check",
        "price": 100,
        "couponCode": "SAVE10",
    }
    request = Request(
        f"{alb_url.rstrip('/')}/productapi/products",
        data=json.dumps(product).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise AssertionError(
                f"expected HTTP 200, received {response.status}"
            )
        created = json.load(response)

    if not isinstance(created, dict):
        raise AssertionError("expected a JSON Product object")
    if (type(created.get("id")) is not int or created["id"] <= 0
            or created.get("name") != product["name"]
            or created.get("description") != product["description"]
            or created.get("couponCode") != product["couponCode"]
            or created.get("price") != 90):
        raise AssertionError(
            "created Product does not match the submitted data"
        )


def main() -> int:
    """Run the acceptance checks and print their outcomes."""
    try:
        outputs = json.loads(OUTPUTS_FILE.read_text(encoding="utf-8"))
        alb_url = read_terraform_output(outputs, "alb_url")
        asg_name = read_terraform_output(outputs, "product_asg_name")
        print(alb_url)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"FAIL infrastructure outputs: {error}")
        return 1

    failed = False
    for label, check, argument in (
        ("Product API", check_product_endpoint, alb_url),
        ("Product ASG", check_product_asg, asg_name),
        ("Product POST", check_product_post, alb_url),
    ):
        try:
            check(argument)
            print(f"PASS {label}")
        except Exception as error:
            print(f"FAIL {label}: {error}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
