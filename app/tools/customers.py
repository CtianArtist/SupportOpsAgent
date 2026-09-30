from app.db.models import Customer, Subscription
from app.services.errors import AuthorizationDenied
from app.tools.context import ToolContext
from app.tools.schemas import CustomerByIdInput, CustomerData, CustomerLookupInput, EmptyInput, SubscriptionData


def get_customer(arguments: CustomerLookupInput, context: ToolContext) -> CustomerData:
    customer = context.db.query(Customer).filter(Customer.id == context.customer_id).one()
    if arguments.email.casefold() != customer.email.casefold():
        raise AuthorizationDenied("This session can only look up its associated customer.")
    return CustomerData(
        customer_id=customer.id,
        name=customer.name,
        email=customer.email,
        account_status=customer.account_status,
    )


def get_customer_by_id(arguments: CustomerByIdInput, context: ToolContext) -> CustomerData:
    if arguments.customer_id != context.customer_id:
        raise AuthorizationDenied("This session cannot access that customer.")
    customer = context.db.query(Customer).filter(Customer.id == context.customer_id).one()
    return CustomerData(
        customer_id=customer.id,
        name=customer.name,
        email=customer.email,
        account_status=customer.account_status,
    )


def get_subscription(arguments: EmptyInput, context: ToolContext) -> SubscriptionData:
    subscription = (
        context.db.query(Subscription)
        .filter(Subscription.customer_id == context.customer_id)
        .one_or_none()
    )
    if subscription is None:
        raise LookupError("No subscription was found for this account.")
    return SubscriptionData(
        plan=subscription.plan,
        price_cents=subscription.price_cents,
        status=subscription.status,
        renews_at=subscription.renews_at,
    )