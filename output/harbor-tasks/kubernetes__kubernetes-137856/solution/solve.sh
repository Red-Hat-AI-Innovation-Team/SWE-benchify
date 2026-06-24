#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/apis/autoscaling/v1/conversion.go b/pkg/apis/autoscaling/v1/conversion.go
index ded80ce8e3621..5c91ab3668fc3 100644
--- a/pkg/apis/autoscaling/v1/conversion.go
+++ b/pkg/apis/autoscaling/v1/conversion.go
@@ -22,6 +22,7 @@ import (
 	autoscalingv1 "k8s.io/api/autoscaling/v1"
 
 	v1 "k8s.io/api/core/v1"
+	"k8s.io/apimachinery/pkg/api/resource"
 	"k8s.io/apimachinery/pkg/conversion"
 	"k8s.io/kubernetes/pkg/apis/autoscaling"
 	"k8s.io/kubernetes/pkg/apis/core"
@@ -82,15 +83,22 @@ func Convert_autoscaling_ObjectMetricSource_To_v1_ObjectMetricSource(in *autosca
 
 func Convert_v1_ObjectMetricSource_To_autoscaling_ObjectMetricSource(in *autoscalingv1.ObjectMetricSource, out *autoscaling.ObjectMetricSource, s conversion.Scope) error {
 	var metricType autoscaling.MetricTargetType
+	var targetValue *resource.Quantity
 	if in.AverageValue == nil {
 		metricType = autoscaling.ValueMetricType
+		targetValue = &in.TargetValue
 	} else {
 		metricType = autoscaling.AverageValueMetricType
+		// Only preserve non-zero targetValue for averageValue metrics.
+		// The v1 type cannot omit the value field, and serializes value:"0", which fails validation on round-trip.
+		if !in.TargetValue.IsZero() {
+			targetValue = &in.TargetValue
+		}
 	}
 
 	out.Target = autoscaling.MetricTarget{
 		Type:         metricType,
-		Value:        &in.TargetValue,
+		Value:        targetValue,
 		AverageValue: in.AverageValue,
 	}
 	out.DescribedObject = autoscaling.CrossVersionObjectReference{
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
