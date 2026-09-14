import pytest
from uuid import uuid4
from app.models.conversation import Conversation
from app.models.message import Message


@pytest.mark.asyncio
async def test_conversations_crud_and_user_isolation(
    client,
    db_session,
    user_a_id,
    user_b_id,
    user_a_headers,
    user_b_headers
):
    # 1. Initially empty for User A
    res = await client.get("/conversations", headers=user_a_headers)
    assert res.status_code == 200
    assert len(res.json()) == 0

    # 2. Insert test conversation belonging to User A
    conv_a_id = uuid4()
    conv_a = Conversation(id=conv_a_id, user_id=user_a_id, title="User A Chat")
    db_session.add(conv_a)
    await db_session.commit()

    msg = Message(
        conversation_id=conv_a_id,
        role="user",
        content="Mensaje confidencial de Usuario A"
    )
    db_session.add(msg)
    await db_session.commit()

    # 3. User A can list and view their conversation
    res_a = await client.get("/conversations", headers=user_a_headers)
    assert res_a.status_code == 200
    conversations_a = res_a.json()
    assert len(conversations_a) == 1
    assert conversations_a[0]["title"] == "User A Chat"

    detail_a = await client.get(f"/conversations/{conv_a_id}", headers=user_a_headers)
    assert detail_a.status_code == 200
    assert detail_a.json()["title"] == "User A Chat"
    assert len(detail_a.json()["messages"]) == 1

    # 4. User B cannot see User A's conversation in their list
    res_b = await client.get("/conversations", headers=user_b_headers)
    assert res_b.status_code == 200
    assert len(res_b.json()) == 0

    # 5. User B receives 404 when trying to access User A's conversation
    detail_b = await client.get(f"/conversations/{conv_a_id}", headers=user_b_headers)
    assert detail_b.status_code == 404

    # 6. User B receives 404 when trying to delete User A's conversation
    del_b = await client.delete(f"/conversations/{conv_a_id}", headers=user_b_headers)
    assert del_b.status_code == 404

    # 7. User A deletes their conversation successfully
    del_a = await client.delete(f"/conversations/{conv_a_id}", headers=user_a_headers)
    assert del_a.status_code == 204

    # 8. Verify deleted
    get_a = await client.get(f"/conversations/{conv_a_id}", headers=user_a_headers)
    assert get_a.status_code == 404
