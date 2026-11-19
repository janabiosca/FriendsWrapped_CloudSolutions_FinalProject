"""Allow a group member's email to register for the dashboard. Does not send email."""
import argparse
import hashlib

import boto3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True, choices=['jana', 'anna', 'helena', 'pati'])
    parser.add_argument('--email', required=True)
    parser.add_argument('--viewer', action='store_true', help='Group access without Spotify collection')
    parser.add_argument('--name', default='Pati')
    parser.add_argument('--region', default='us-east-1')
    parser.add_argument('--table', default='sfw-dev-connect')
    args = parser.parse_args()
    email = args.email.strip().casefold()
    key = 'EMAIL#' + hashlib.sha256(email.encode()).hexdigest()
    boto3.resource('dynamodb', region_name=args.region).Table(args.table).put_item(
        Item={'id': key, 'user_id': args.user_id, 'group_id': 'friends'},
        ConditionExpression='attribute_not_exists(id) OR user_id = :u',
        ExpressionAttributeValues={':u': args.user_id})
    if args.viewer:
        boto3.resource('dynamodb', region_name=args.region).Table('sfw-dev').put_item(
            Item={'PK': 'GROUP#friends', 'SK': 'VIEWER#' + args.user_id,
                  'user_id': args.user_id, 'display_name': args.name})
    print(args.user_id + ': dashboard registration enabled')


if __name__ == '__main__':
    main()
