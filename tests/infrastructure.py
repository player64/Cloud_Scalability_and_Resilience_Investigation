#!/usr/bin/env python3
"""Check infrastructure and manage Product test data."""

import argparse
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


def parse_infra_output() -> tuple[str, str]:
    outputs = json.loads(OUTPUTS_FILE.read_text(encoding="utf-8"))
    alb_url = read_terraform_output(outputs, "alb_url")
    asg_name = read_terraform_output(outputs, "product_asg_name")
    return alb_url, asg_name


def product_url(alb_url: str) -> str:
    return f"{alb_url.rstrip('/')}/productapi/products"


def check_product_endpoint(alb_url: str) -> None:
    """Require an HTTP 200 response containing a populated Product object."""
    request = Request(product_url(alb_url), method="GET")

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

    if (
            instance["LifecycleState"] != "InService"
            or instance["HealthStatus"] != "Healthy"
    ):
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
        product_url(alb_url),
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

    if (
            type(created.get("id")) is not int
            or created["id"] <= 0
            or created.get("name") != product["name"]
            or created.get("description") != product["description"]
            or created.get("couponCode") != product["couponCode"]
            or created.get("price") != 90
    ):
        raise AssertionError(
            "created Product does not match the submitted data"
        )


def seed_products(alb_url: str, count: int) -> None:
    """Populate the database using the Spring Boot seed endpoint."""
    url = f"{product_url(alb_url)}/seed?count={count}"

    request = Request(
        url,
        data=b"",
        method="POST",
    )

    with urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(
                f"Seed failed with HTTP {response.status}"
            )
        created = json.load(response)

    print(f"Seeded {created} products.")


def delete_products(alb_url: str) -> None:
    """Delete all products using the Spring Boot DELETE endpoint."""
    request = Request(
        product_url(alb_url),
        method="DELETE",
    )

    with urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(
                f"Delete failed with HTTP {response.status}"
            )
        deleted = json.load(response)

    print(f"Deleted {deleted} products.")


def test_initial_infra(alb_url: str, asg_name: str) -> int:
    """Run the acceptance checks and print their outcomes."""
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Product infrastructure and test data management."
    )

    parser.add_argument(
        "type",
        choices=["test_infra", "seed", "delete"],
        help="Operation to execute",
    )

    parser.add_argument(
        "--count",
        type=int,
        help="Number of products to seed",
    )

    args = parser.parse_args()

    if args.type == "seed":
        if args.count is None or args.count <= 0:
            parser.error("seed requires --count with a positive integer")
    elif args.count is not None:
        parser.error("--count is only valid for seed")

    try:
        alb_url, asg_name = parse_infra_output()

        if args.type == "test_infra":
            return test_initial_infra(alb_url, asg_name)

        if args.type == "seed":
            seed_products(alb_url, args.count)

        elif args.type == "delete":
            delete_products(alb_url)

    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())