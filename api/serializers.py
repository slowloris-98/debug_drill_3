from rest_framework import serializers

from core.models import UsageRecord


class UsageRecordSerializer(serializers.ModelSerializer):
    amount_cents = serializers.SerializerMethodField()

    class Meta:
        model = UsageRecord
        fields = [
            "id",
            "external_id",
            "metric",
            "quantity",
            "unit_cost_cents",
            "amount_cents",
            "recorded_at",
        ]
        read_only_fields = ["id", "amount_cents"]

    def get_amount_cents(self, obj):
        return obj.quantity * obj.unit_cost_cents
