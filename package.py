#!/usr/bin/env python
import argparse
import boto3
import os
import shutil
import subprocess
import tempfile
import venv
import zipfile


# TODO
# * Set up the role with permissions on the DynamoDB table and CloudWatch rules and lambda
# * Set up the API gateway for Lambda
# * Set retention policy on cloudwatch log stream
# * Cleanup command


REQUIREMENTS = ["requests", "boto3", "dynamo3"]

ENV = {"OAUTH_TOKEN": None}


def set_env():
    for key in ENV:
        if key not in os.environ:
            raise ValueError("Missing environment variable %s" % key)
        ENV[key] = os.environ[key]


def _build_lambda_bundle():
    """ Build the lambda bundle """
    venv_dir = tempfile.mkdtemp()
    try:
        print("Creating virtualenv %s" % venv_dir)
        venv.create(venv_dir, with_pip=True)
        print("Installing dependencies into virtualenv")
        pip = os.path.join(venv_dir, "bin", "pip")
        subprocess.check_call([pip, "install"] + REQUIREMENTS)

        bundle = "%s/output.zip" % venv_dir
        zipf = zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED)

        site_packages = os.path.join(venv_dir, "lib", "site-packages")
        if not os.path.exists(site_packages):
            subdir = [
                f
                for f in os.listdir(os.path.join(venv_dir, "lib"))
                if f.startswith("python")
            ][0]
            site_packages = os.path.join(venv_dir, "lib", subdir, "site-packages")

        for root, dirs, files in os.walk(site_packages):
            for filename in files:
                fullpath = os.path.join(root, filename)
                zipf.write(fullpath, os.path.relpath(fullpath, site_packages))

        zipf.write("lambda_script.py", "lambda_script.py")

        zipf.close()
        with open(bundle, "rb") as ifile:
            return ifile.read()
    finally:
        shutil.rmtree(venv_dir)


def _create_dynamo_table(region):
    client = boto3.client("dynamodb", region_name=region)

    try:
        client.describe_table(TableName="CaptionarySubmissions")
    except client.exceptions.ResourceNotFoundException:
        pass
    else:
        return

    print("Creating DynamoDB table")
    client.create_table(
        TableName="CaptionarySubmissions",
        KeySchema=[
            {"AttributeName": "channel", "KeyType": "HASH"},
            {"AttributeName": "text", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "channel", "AttributeType": "S"},
            {"AttributeName": "text", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )


def main():
    """ Bundle and upload script to AWS Lambda """

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "-n",
        help="Name of the AWS Lambda function to " " create (default %(default)s)",
        default="Captionary",
    )
    parser.add_argument(
        "-r",
        "--region",
        help="The AWS region to use (default %(default)s)",
        default="us-west-1",
    )

    args = parser.parse_args()

    set_env()

    _create_dynamo_table(args.region)

    lam = boto3.client("lambda", region_name=args.region)
    func_arn = None
    role_arn = "arn:aws:iam::549234236095:role/service-role/Captionary"
    bundle = _build_lambda_bundle()
    try:
        func = lam.get_function(FunctionName=args.n)
    except lam.exceptions.ResourceNotFoundException:
        print("Creating lambda function %r" % args.n)
        func = lam.create_function(
            FunctionName=args.n,
            Runtime="python3.6",
            Handler="lambda_script.lambda_handler",
            Code={"ZipFile": bundle},
            Environment={"Variables": ENV},
            Description="Captionary bot",
            Timeout=30,
            Publish=True,
            Role=role_arn,
        )
        print("TODO you will now need to create an API gateway")
    else:
        func_arn = func["Configuration"]["FunctionArn"]
        print("Updating Lambda function %r" % args.n)
        func = lam.update_function_code(
            FunctionName=func_arn, ZipFile=bundle, Publish=True
        )

    print("Done")


if __name__ == "__main__":
    main()
